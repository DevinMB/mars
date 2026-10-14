"""Client for the Flink SQL Gateway REST API.

The gateway is how MARS turns a SQL document into a running Flink job. Two things
about it shape this module:

* **Sessions are ephemeral.** DDL registered in a session disappears with it. MARS
  therefore keeps table definitions as catalog fragments in its own database and
  replays the ones a job declares ahead of that job's statement, every time it is
  submitted. That avoids running a metastore and keeps each job's dependencies
  explicit and reviewable.
* **Errors arrive as a stack trace, not a message.** A Flink SQL error surfaces as
  a multi-kilobyte Java trace inside an ``errors`` array. :func:`_friendly_error`
  pulls out the part a human needs and keeps the rest for the detail pane.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)

# A Flink job id as it appears in an INSERT result: 32 lowercase hex characters.
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")

# The first line of a Flink SQL failure that actually says what went wrong.
_USEFUL_CAUSE = re.compile(
    r"^(?:org\.apache\.flink\.table\.api\.\w+Exception|"
    r"org\.apache\.calcite\.sql\.validate\.\w+Exception|"
    r"java\.lang\.IllegalArgumentException):\s*(?P<msg>.+)$",
    re.MULTILINE,
)


class GatewayError(RuntimeError):
    """A statement failed. Carries both a readable summary and the raw trace."""

    def __init__(self, summary: str, detail: str = "", statement: str = "") -> None:
        super().__init__(summary)
        self.summary = summary
        self.detail = detail
        self.statement = statement


@dataclass
class StatementResult:
    """Outcome of one executed statement."""

    operation_handle: str
    statement: str
    job_id: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)


class SqlGatewayClient:
    """Thin async wrapper over the gateway's v1 REST API."""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def info(self) -> dict[str, Any]:
        async with self._client() as c:
            r = await c.get("/v1/info")
            r.raise_for_status()
            return r.json()

    async def open_session(self, properties: dict[str, str] | None = None) -> str:
        async with self._client() as c:
            r = await c.post("/v1/sessions", json={"properties": properties or {}})
            r.raise_for_status()
            return r.json()["sessionHandle"]

    async def close_session(self, session: str) -> None:
        async with self._client() as c:
            try:
                await c.delete(f"/v1/sessions/{session}")
            except httpx.HTTPError:
                # A session that is already gone is not a problem worth raising.
                pass

    async def execute(self, session: str, statement: str) -> StatementResult:
        """Runs one statement to completion and returns its first result page."""
        async with self._client() as c:
            r = await c.post(
                f"/v1/sessions/{session}/statements", json={"statement": statement}
            )
            if r.status_code >= 400:
                raise GatewayError(
                    _friendly_error(r.text), detail=r.text, statement=statement
                )
            handle = r.json()["operationHandle"]

            status = await self._await_completion(c, session, handle, statement)
            result = StatementResult(operation_handle=handle, statement=statement)

            if status == "ERROR":
                detail = await self._fetch_raw(c, session, handle)
                raise GatewayError(
                    _friendly_error(detail), detail=detail, statement=statement
                )

            payload = await self._fetch_result(c, session, handle)
            if payload is not None:
                _populate(result, payload)
            return result

    async def execute_script(
        self, session: str, statements: list[str]
    ) -> list[StatementResult]:
        """Runs statements in order, stopping at the first failure."""
        out: list[StatementResult] = []
        for stmt in statements:
            out.append(await self.execute(session, stmt))
        return out

    async def validate(self, session: str, statement: str) -> str:
        """Type-checks a statement without running it, and returns Flink's plan.

        ``EXPLAIN PLAN FOR`` compiles the query and builds a plan but submits no
        job, which is what makes a Create-job button in the console safe to press.
        The plan names every table the statement reads and writes.
        """
        stripped = statement.strip().rstrip(";")
        result = await self.execute(session, f"EXPLAIN PLAN FOR {stripped}")
        return "\n".join(str(cell) for row in result.rows for cell in row)

    async def select_rows(
        self,
        session: str,
        statement: str,
        limit: int,
        budget: float = 45.0,
    ) -> StatementResult:
        """Runs a SELECT and collects rows as they stream back.

        Results do not arrive with the response. The operation reports FINISHED as
        soon as the job is *accepted*, and rows then appear across a chain of
        result pages -- empty ones at first, because a Flink job has to be
        scheduled and started before it reads anything. Against a live topic here
        the first row landed on page 57, roughly twenty seconds in, so anything
        that reads only the first page concludes the topic is empty.

        The operation is always cancelled afterwards: a streaming SELECT is a real
        job occupying a slot, and abandoning it on a small cluster is an outage.
        """
        deadline = time.monotonic() + budget
        result = StatementResult(operation_handle="", statement=statement)

        async with self._client() as c:
            r = await c.post(
                f"/v1/sessions/{session}/statements", json={"statement": statement}
            )
            if r.status_code >= 400:
                raise GatewayError(
                    _friendly_error(r.text), detail=r.text, statement=statement
                )
            handle = r.json()["operationHandle"]
            result.operation_handle = handle

            try:
                status = await self._await_completion(c, session, handle, statement)
                if status == "ERROR":
                    detail = await self._fetch_raw(c, session, handle)
                    raise GatewayError(
                        _friendly_error(detail), detail=detail, statement=statement
                    )

                uri = f"/v1/sessions/{session}/operations/{handle}/result/0"
                while time.monotonic() < deadline:
                    page = await c.get(uri)
                    if page.status_code >= 400:
                        break
                    payload = page.json()

                    body = payload.get("results") or {}
                    if body.get("columns") and not result.columns:
                        result.columns = [
                            col.get("name", "") for col in body["columns"]
                        ]
                    for row in body.get("data", []):
                        # A streaming result can retract rows it already sent;
                        # for a sample those are noise, not data.
                        if row.get("kind") in ("DELETE", "UPDATE_BEFORE"):
                            continue
                        result.rows.append(row.get("fields", []))

                    if len(result.rows) >= limit or payload.get("resultType") == "EOS":
                        break
                    next_uri = payload.get("nextResultUri")
                    if not next_uri:
                        break
                    uri = next_uri
                    await asyncio.sleep(0.25)
            finally:
                await self._cancel(c, session, handle)

        del result.rows[limit:]
        return result

    async def _cancel(self, c: httpx.AsyncClient, session: str, handle: str) -> None:
        for path in (f"/v1/sessions/{session}/operations/{handle}/cancel",
                     f"/v1/sessions/{session}/operations/{handle}/close"):
            try:
                await c.post(path) if path.endswith("cancel") else await c.delete(path)
            except httpx.HTTPError as exc:  # pragma: no cover - best effort
                log.debug("Preview cleanup on %s: %s", path, exc)

    # -- internals ----------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base, timeout=self._timeout)

    async def _await_completion(
        self, c: httpx.AsyncClient, session: str, handle: str, statement: str
    ) -> str:
        delay = 0.1
        waited = 0.0
        # A DDL statement settles in milliseconds; an INSERT returns as soon as the
        # job is accepted, so this loop is short in both cases.
        while waited < self._timeout:
            r = await c.get(f"/v1/sessions/{session}/operations/{handle}/status")
            if r.status_code >= 400:
                raise GatewayError(
                    _friendly_error(r.text), detail=r.text, statement=statement
                )
            status = r.json()["status"]
            if status in ("FINISHED", "ERROR", "CANCELED"):
                return status
            await asyncio.sleep(delay)
            waited += delay
            delay = min(delay * 1.5, 1.0)
        raise GatewayError(
            f"Statement did not settle within {self._timeout:.0f}s", statement=statement
        )

    async def _fetch_result(
        self, c: httpx.AsyncClient, session: str, handle: str
    ) -> dict[str, Any] | None:
        r = await c.get(f"/v1/sessions/{session}/operations/{handle}/result/0")
        if r.status_code >= 400:
            # Some statements carry no result set; that is not an error.
            return None
        return r.json()

    async def _fetch_raw(self, c: httpx.AsyncClient, session: str, handle: str) -> str:
        try:
            r = await c.get(f"/v1/sessions/{session}/operations/{handle}/result/0")
            return r.text
        except httpx.HTTPError as exc:  # pragma: no cover - network edge
            return str(exc)


def _populate(result: StatementResult, payload: dict[str, Any]) -> None:
    results = payload.get("results") or {}
    columns = [c.get("name", "") for c in results.get("columns", [])]
    result.columns = columns

    for row in results.get("data", []):
        fields = row.get("fields", [])
        result.rows.append(fields)
        for value in fields:
            if isinstance(value, str) and _JOB_ID.match(value):
                result.job_id = value


def _friendly_error(raw: str) -> str:
    """Reduces a Flink failure to the one line that explains it.

    The gateway returns ``{"errors": ["Internal server error.", "<9kB trace>"]}``.
    Two things matter: the body must be JSON-decoded first, because otherwise the
    newlines are still ``\\n`` escapes and every line-oriented pattern matches the
    whole blob; and the *deepest* ``Caused by`` is the real reason, since the outer
    frames only say that fetching results failed.
    """
    if not raw:
        return "Statement failed with no detail"

    text = _decoded_error_text(raw)

    # The last "Caused by" is the root cause; earlier ones are gateway plumbing.
    causes = re.findall(
        r"Caused by:\s*[\w.$]*?(?:Exception|Error):\s*(.+)", text
    )
    if causes:
        return _tidy(causes[-1])

    match = _USEFUL_CAUSE.search(text)
    if match:
        return _tidy(match.group("msg"))

    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith(("at ", "...", "<", "{", "}")):
            return _tidy(line)
    return "Statement failed"


def _decoded_error_text(raw: str) -> str:
    """Pulls the human-readable text out of a gateway error body."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw

    if isinstance(parsed, dict):
        errors = parsed.get("errors")
        if isinstance(errors, list):
            # Longest entry first: the short one is always "Internal server error."
            return "\n".join(sorted((str(e) for e in errors), key=len, reverse=True))
        if isinstance(errors, str):
            return errors
    return raw


def _tidy(message: str) -> str:
    """Trims noise that is constant in a MARS deployment.

    Every table lives in the one default catalog, so spelling that out in an error
    only makes the useful part -- the table name -- harder to find.
    """
    text = " ".join(message.split())
    text = text.replace("`default_catalog`.`default_database`.", "")
    text = re.sub(r"\s*in any of the catalogs \[[^\]]*\],?", "", text)
    return text.strip()[:400]
