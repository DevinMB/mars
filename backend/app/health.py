"""Asks a connector's target whether it is there, before a job depends on it.

A misconfigured sink does not fail when you save it. It fails minutes later, on a
TaskManager, as a restart loop with a Java stack trace -- and the CouchDB sink
fails with exactly that today: "Could not find any factory", or a connection
refused buried in `CouchDbClient.checkDatabaseExists`. Everything needed to catch
it was available at the moment someone pressed Save.

One honest limitation, stated wherever a result is shown: this probe runs from the
console, and the job will run from a TaskManager. They are usually the same
network and occasionally are not. A probe that succeeds is strong evidence and not
a guarantee; a probe that fails is almost always a real problem.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

TIMEOUT = 8.0


@dataclass
class HealthResult:
    # None when there is nothing meaningful to check, which is not a failure.
    ok: bool | None
    detail: str = ""
    hint: str | None = None


async def _tcp(host: str, port: int) -> tuple[bool, str]:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=TIMEOUT
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # pragma: no cover - close races are not interesting
            pass
        return True, f"{host}:{port} accepted a connection"
    except asyncio.TimeoutError:
        return False, f"{host}:{port} did not answer within {TIMEOUT:.0f}s"
    except OSError as exc:
        return False, f"{host}:{port} refused the connection ({exc.strerror or exc})"


async def _couchdb(options: dict[str, str]) -> HealthResult:
    url = (options.get("url") or "").rstrip("/")
    db = options.get("db") or ""
    if not url or not db:
        return HealthResult(None, "Set a URL and a database first.")

    headers = {}
    user, password = options.get("username"), options.get("password")
    if user:
        token = base64.b64encode(f"{user}:{password or ''}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(f"{url}/{db}", headers=headers)
    except httpx.HTTPError as exc:
        return HealthResult(
            False,
            f"Could not reach {url}. {type(exc).__name__}",
            "Check the address, and that it is reachable from the MARS container "
            "rather than only from your laptop.",
        )

    if r.status_code == 200:
        try:
            count = r.json().get("doc_count")
        except ValueError:
            count = None
        detail = f"Database '{db}' exists"
        if count is not None:
            detail += f" and holds {count} documents"
        return HealthResult(True, detail + ".")
    if r.status_code == 404:
        return HealthResult(
            False,
            f"Reachable, but there is no database called '{db}'.",
            "CouchDB does not create one on demand. Create it, or correct the name.",
        )
    if r.status_code in (401, 403):
        return HealthResult(
            False,
            "The server rejected these credentials.",
            "Check the username and password secrets.",
        )
    return HealthResult(False, f"The server answered {r.status_code}.")


async def _kafka(options: dict[str, str]) -> HealthResult:
    servers = options.get("properties.bootstrap.servers") or ""
    if not servers:
        return HealthResult(None, "Set the bootstrap servers first.")

    results = []
    for item in [s.strip() for s in servers.split(",") if s.strip()]:
        host, _, port = item.rpartition(":")
        if not host or not port.isdigit():
            results.append((False, f"'{item}' is not host:port"))
            continue
        results.append(await _tcp(host, int(port)))

    if not results:
        return HealthResult(None, "No bootstrap servers to check.")
    if all(ok for ok, _ in results):
        return HealthResult(
            True,
            "; ".join(detail for _, detail in results)
            + ". This checks the broker answers, not that the topic exists.",
        )
    return HealthResult(
        False,
        "; ".join(detail for ok, detail in results if not ok),
        "Kafka must be reachable from the MARS container and from the TaskManager, "
        "which on this setup means an address, not 'localhost'.",
    )


async def _base_url(options: dict[str, str], key: str, what: str) -> HealthResult:
    url = (options.get(key) or "").rstrip("/")
    if not url:
        return HealthResult(None, f"Set the {what} first.")
    parts = urlsplit(url)
    if not parts.hostname:
        return HealthResult(False, f"'{url}' is not a URL.")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as c:
            r = await c.get(url)
    except httpx.HTTPError as exc:
        return HealthResult(
            False,
            f"Could not reach {url}. {type(exc).__name__}",
            "Check the address is reachable from the MARS container.",
        )
    # Any answer means something is listening and speaking HTTP. Authorisation is
    # checked when a record is actually sent, and a 401 here would be misleading.
    return HealthResult(True, f"{url} answered {r.status_code}.")


async def probe(connector: str, options: dict[str, str]) -> HealthResult:
    """Checks what can be checked. Secrets must already be resolved."""
    try:
        if connector == "couchdb":
            return await _couchdb(options)
        if connector == "kafka":
            return await _kafka(options)
        if connector == "home-assistant":
            return await _base_url(options, "base-url", "base URL")
        if connector == "http":
            return await _base_url(options, "base-url", "base URL")
    except Exception as exc:  # pragma: no cover - a probe must never break a save
        log.warning("Health probe for %s failed unexpectedly: %s", connector, exc)
        return HealthResult(False, f"The check itself failed: {exc}")

    return HealthResult(None, f"There is nothing to check for a {connector} table.")
