"""The model MARS talks to.

One provider, configured in Administration, used by every feature that needs a
model. Features call `complete()` and never know which backend answered, so a
site can run a local Ollama, a hosted API, or anything speaking the OpenAI shape
without a feature caring.

Three rules this module keeps, because each is easy to get wrong once and hard to
notice afterwards:

* **The key lives in the secret store.** It is referenced by name, decrypted for
  the duration of one request, and never returned by the API.
* **Failures are reported, never guessed at.** A model that is unreachable, or a
  name that does not exist on the server, produces a clear message rather than an
  empty completion that reads like a bad answer.
* **Nothing is sent anywhere by default.** Until an administrator configures a
  provider and enables it, every AI feature is simply off.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)

OLLAMA = "ollama"
ANTHROPIC = "anthropic"
OPENAI = "openai-compatible"

KINDS = (OLLAMA, ANTHROPIC, OPENAI)

# Only Anthropic is a hosted service with a fixed address; the others are
# wherever the operator runs them.
DEFAULT_BASE_URL = {ANTHROPIC: "https://api.anthropic.com"}

# What each kind needs before it can be used at all.
NEEDS_KEY = {ANTHROPIC, OPENAI}

# How a credential is presented.
AUTH_NONE = "none"
AUTH_BEARER = "bearer"
AUTH_HEADER = "header"
AUTH_BASIC = "basic"
AUTH_METHODS = (AUTH_NONE, AUTH_BEARER, AUTH_HEADER, AUTH_BASIC)

# What each provider usually expects, offered as a starting point rather than
# enforced -- a gateway in front of any of them can change the answer.
SUGGESTED_AUTH = {
    OLLAMA: (AUTH_NONE, ""),
    ANTHROPIC: (AUTH_HEADER, "x-api-key"),
    OPENAI: (AUTH_BEARER, ""),
}

# Headers a provider needs regardless of how it authenticates.
REQUIRED_HEADERS = {ANTHROPIC: {"anthropic-version": "2023-06-01"}}


class AiError(RuntimeError):
    """Something went wrong talking to the model. The message is user-facing."""


@dataclass
class AiStatus:
    ok: bool
    detail: str = ""
    models: list[str] = field(default_factory=list)


@dataclass
class AiConfig:
    kind: str = OLLAMA
    base_url: str = ""
    model: str = ""
    api_key: str | None = None
    timeout_seconds: int = 120
    auth_method: str = AUTH_NONE
    auth_header: str = ""
    auth_username: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)
    temperature: str = "0"
    max_tokens: int = 1500

    @property
    def needs_credential(self) -> bool:
        return self.auth_method in (AUTH_BEARER, AUTH_HEADER, AUTH_BASIC)

    @property
    def configured(self) -> bool:
        if self.kind not in KINDS or not self.model:
            return False
        if self.needs_credential and not self.api_key:
            return False
        if self.auth_method == AUTH_HEADER and not self.auth_header.strip():
            return False
        return bool(self.base_url or DEFAULT_BASE_URL.get(self.kind))

    @property
    def url(self) -> str:
        return (self.base_url or DEFAULT_BASE_URL.get(self.kind, "")).rstrip("/")


class AiClient:
    def __init__(self, config: AiConfig) -> None:
        self._c = config

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._c.url, timeout=self._c.timeout_seconds)

    async def status(self) -> AiStatus:
        """Checks the provider answers, and that the chosen model exists there.

        Listing the models matters more than a bare ping: the most common
        misconfiguration is a model name that is not pulled on the server, and
        that failure otherwise appears only when a user first tries to use it.
        """
        if not self._c.configured:
            return AiStatus(ok=False, detail="No model is configured.")
        try:
            async with self._client() as c:
                if self._c.kind == OLLAMA:
                    r = await c.get("/api/tags", headers=self._headers())
                    r.raise_for_status()
                    models = [m.get("name", "") for m in r.json().get("models", [])]
                elif self._c.kind == OPENAI:
                    r = await c.get("/v1/models", headers=self._headers())
                    r.raise_for_status()
                    models = [m.get("id", "") for m in r.json().get("data", [])]
                else:
                    # Anthropic has no free health endpoint, so the cheapest
                    # honest check is a one-token completion.
                    await self.complete("Reply with: ok", max_tokens=8)
                    return AiStatus(ok=True, detail="Reachable.", models=[self._c.model])
        except httpx.HTTPStatusError as exc:
            return AiStatus(ok=False, detail=_http_message(exc))
        except httpx.HTTPError as exc:
            return AiStatus(ok=False, detail=f"Could not reach {self._c.url}. {_why(exc)}")
        except AiError as exc:
            return AiStatus(ok=False, detail=str(exc))

        if models and self._c.model not in models:
            # Ollama reports "qwen3:8b"; a user may have typed "qwen3".
            near = [m for m in models if m.split(":")[0] == self._c.model.split(":")[0]]
            hint = f" Did you mean {near[0]}?" if near else ""
            return AiStatus(
                ok=False,
                detail=(
                    f"Reachable, but '{self._c.model}' is not on that server."
                    f"{hint}"
                ),
                models=models,
            )
        return AiStatus(ok=True, detail="Reachable, and the model is present.", models=models)

    def _headers(self) -> dict[str, str]:
        """Credential, provider requirements, then the operator's own headers.

        Applied in that order deliberately: an operator's explicit header is the
        most specific statement of intent, so it wins over anything guessed here.
        """
        headers: dict[str, str] = {"content-type": "application/json"}
        key = self._c.api_key or ""
        method = self._c.auth_method

        if method == AUTH_BEARER and key:
            headers["Authorization"] = f"Bearer {key}"
        elif method == AUTH_HEADER and key and self._c.auth_header.strip():
            headers[self._c.auth_header.strip()] = key
        elif method == AUTH_BASIC and key:
            token = base64.b64encode(
                f"{self._c.auth_username}:{key}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {token}"

        headers.update(REQUIRED_HEADERS.get(self._c.kind, {}))
        headers.update({k: v for k, v in self._c.extra_headers.items() if k})
        return headers

    async def complete(
        self, prompt: str, system: str = "", max_tokens: int = 1500
    ) -> str:
        """One completion. Raises AiError with something a person can act on."""
        if not self._c.configured:
            raise AiError("No model is configured. An administrator sets one up "
                          "under Administration.")
        try:
            async with self._client() as c:
                if self._c.kind == OLLAMA:
                    r = await c.post("/api/generate", headers=self._headers(), json={
                        "model": self._c.model,
                        "prompt": prompt,
                        "system": system,
                        "stream": False,
                        "think": False,
                        "options": {"temperature": _number(self._c.temperature)},
                    })
                    r.raise_for_status()
                    return (r.json().get("response") or "").strip()

                if self._c.kind == ANTHROPIC:
                    body = {
                        "model": self._c.model,
                        "max_tokens": max_tokens,
                        "temperature": _number(self._c.temperature),
                        "messages": [{"role": "user", "content": prompt}],
                    }
                    if system:
                        body["system"] = system
                    r = await c.post("/v1/messages", json=body, headers=self._headers())
                    r.raise_for_status()
                    parts = [
                        b.get("text", "")
                        for b in r.json().get("content", [])
                        if b.get("type") == "text"
                    ]
                    return "".join(parts).strip()

                messages = ([{"role": "system", "content": system}] if system else []) + [
                    {"role": "user", "content": prompt}
                ]
                r = await c.post("/v1/chat/completions", json={
                    "model": self._c.model,
                    "max_tokens": max_tokens,
                    "temperature": _number(self._c.temperature),
                    "messages": messages,
                }, headers=self._headers())
                r.raise_for_status()
                choices = r.json().get("choices") or []
                if not choices:
                    raise AiError("The model returned no answer.")
                return (choices[0].get("message", {}).get("content") or "").strip()
        except httpx.HTTPStatusError as exc:
            raise AiError(_http_message(exc)) from exc
        except httpx.HTTPError as exc:
            raise AiError(f"Could not reach {self._c.url}. {_why(exc)}") from exc


def _number(value: str, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _why(exc: httpx.HTTPError) -> str:
    """A reason, even when the exception has no message.

    httpx raises ConnectTimeout and friends with an empty string, which rendered
    as "Could not reach http://host:11434: " and told the reader nothing about
    whether it was the wrong address, a firewall, or a slow server.
    """
    text = str(exc).strip()
    if text:
        return text
    return {
        "ConnectTimeout": "It did not answer in time; check the address and that it is running.",
        "ConnectError": "The connection was refused; check the address and the port.",
        "ReadTimeout": "It accepted the connection but did not reply in time.",
        "PoolTimeout": "No connection was available in time.",
    }.get(type(exc).__name__, f"{type(exc).__name__}.")


def _http_message(exc: httpx.HTTPStatusError) -> str:
    """Turns a provider's HTTP failure into something worth reading."""
    code = exc.response.status_code
    if code in (401, 403):
        return "The provider rejected the API key."
    if code == 404:
        return "The provider returned 404. Check the base URL and the model name."
    if code == 429:
        return "The provider is rate limiting; try again shortly."
    body = ""
    try:
        payload = exc.response.json()
        body = str(payload.get("error") or payload.get("message") or "")[:200]
    except ValueError:
        body = exc.response.text[:200]
    return f"The provider returned {code}. {body}".strip()
