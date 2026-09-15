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

    @property
    def configured(self) -> bool:
        if self.kind not in KINDS or not self.model:
            return False
        if self.kind in NEEDS_KEY and not self.api_key:
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
                    r = await c.get("/api/tags")
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
        if self._c.kind == ANTHROPIC:
            return {
                "x-api-key": self._c.api_key or "",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        if self._c.kind == OPENAI:
            return {"Authorization": f"Bearer {self._c.api_key or ''}"}
        return {}

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
                    r = await c.post("/api/generate", json={
                        "model": self._c.model,
                        "prompt": prompt,
                        "system": system,
                        "stream": False,
                        "think": False,
                    })
                    r.raise_for_status()
                    return (r.json().get("response") or "").strip()

                if self._c.kind == ANTHROPIC:
                    body = {
                        "model": self._c.model,
                        "max_tokens": max_tokens,
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
