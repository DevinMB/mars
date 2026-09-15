"""Reads a few real records from a source, so a job can be written against facts.

Most sources here carry an opaque JSON document in a single STRING column --
that is what "raw passthrough" means -- so the declared schema says `record_key,
doc` and tells the author nothing about what is inside. The only honest way to
answer "what fields can I use?" is to look at a record.

Two things this must not do, both of which would be easy to get wrong:

* **Disturb the running job.** A preview that reused the catalog entry's consumer
  group would join that group and take partitions from the job that owns it.
  Every preview therefore gets a throwaway group id and an explicit start
  position, so it never reads or commits the real one's offsets.
* **Leave a job running.** A streaming SELECT is a Flink job holding a slot. On a
  small cluster a handful of abandoned previews is an outage, so the operation is
  cancelled and the session closed on every path out of here, including timeout.
"""
from __future__ import annotations

import json
import logging
import re
import secrets as _secrets
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from .gateway import GatewayError, SqlGatewayClient
from .guards import columns_of, parse_options, strip_noise
from .models import CatalogEntry
from .secrets import SecretStore

log = logging.getLogger(__name__)

# Options that must never be inherited from the catalog entry.
_OVERRIDDEN = {"properties.group.id", "scan.startup.mode", "scan.startup.specific-offsets",
               "scan.startup.timestamp-millis"}


@dataclass
class FieldGuess:
    name: str
    type: str
    example: str | None = None


@dataclass
class SampleResult:
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    # For each column holding JSON objects, the fields found inside it.
    nested: dict[str, list[FieldGuess]] = field(default_factory=dict)
    truncated: bool = False
    error: str | None = None


def _kind_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "BIGINT"
    if isinstance(value, float):
        return "DOUBLE"
    if isinstance(value, str):
        return "STRING"
    if isinstance(value, list):
        return "ARRAY"
    return "ROW"


def infer_nested(values: list[Any]) -> list[FieldGuess]:
    """Field names and types found inside JSON documents from one column.

    Every record is inspected, not just the first: these documents are not
    schema-checked anywhere, and a field that is absent from record one but
    present in record four is exactly the kind of thing worth showing.
    """
    seen: dict[str, FieldGuess] = {}
    for raw in values:
        if not isinstance(raw, str):
            continue
        try:
            doc = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(doc, dict):
            continue
        for key, value in doc.items():
            kind = _kind_of(value)
            existing = seen.get(key)
            if existing is None:
                example = None
                if value is not None and not isinstance(value, (dict, list)):
                    example = str(value)[:60]
                seen[key] = FieldGuess(name=key, type=kind, example=example)
            elif existing.type != kind and kind != "null":
                # A field that is a number in one record and a string in another
                # is worth flagging rather than quietly showing the first guess.
                if existing.type == "null":
                    existing.type = kind
                elif kind not in existing.type:
                    existing.type = f"{existing.type} or {kind}"
    return sorted(seen.values(), key=lambda f: f.name)


def build_preview_ddl(entry: CatalogEntry, table: str, start: str) -> str:
    """Rebuilds a source's DDL as a throwaway table that cannot disturb anything."""
    columns = columns_of(entry.sql_text)
    if not columns:
        raise ValueError(
            f"Could not read the column list of '{entry.name}', so there is nothing "
            f"to preview."
        )
    options = {k: v for k, v in parse_options(entry.sql_text).items()
               if k not in _OVERRIDDEN}

    if options.get("connector") == "kafka":
        # A fresh group every time: joining the real one would take partitions
        # away from the job that owns it.
        options["properties.group.id"] = f"mars-preview-{_secrets.token_hex(4)}"
        options["scan.startup.mode"] = (
            "latest-offset" if start == "latest" else "earliest-offset"
        )

    column_sql = ",\n  ".join(f"`{name}` {type_}" for name, type_ in columns)
    option_sql = ",\n  ".join(
        "'%s' = '%s'" % (k, v.replace("'", "''")) for k, v in options.items()
    )
    return f"CREATE TABLE `{table}` (\n  {column_sql}\n) WITH (\n  {option_sql}\n)"


async def sample_source(
    gateway: SqlGatewayClient,
    store: SecretStore,
    db: Session,
    entry: CatalogEntry,
    limit: int = 5,
    start: str = "earliest",
) -> SampleResult:
    table = f"mars_preview_{_secrets.token_hex(4)}"
    try:
        ddl = build_preview_ddl(entry, table, start)
    except ValueError as exc:
        return SampleResult(error=str(exc))

    session = await gateway.open_session({"parallelism.default": "1"})
    try:
        await gateway.execute(session, store.resolve(db, ddl))
        wanted = max(1, min(limit, 50))
        result = await gateway.select_rows(
            session, f"SELECT * FROM `{table}` LIMIT {wanted}", wanted
        )
        out = SampleResult(columns=list(result.columns), rows=[list(r) for r in result.rows])
    except GatewayError as exc:
        message = store.redact(db, exc.summary)
        if "did not settle" in message:
            message = (
                "The cluster did not start a query within the time limit. It may have "
                "no free slots."
            )
        return SampleResult(error=message)
    finally:
        # Always: a streaming SELECT is a job holding a slot.
        try:
            await gateway.close_session(session)
        except Exception as exc:  # pragma: no cover - cleanup must not mask results
            log.warning("Could not close preview session: %s", exc)

    if not out.rows:
        out.error = (
            "No records arrived within the time limit. The topic may be empty, or "
            "there may be nothing new to read from the chosen start position."
        )
        return out

    for index, name in enumerate(out.columns):
        values = [row[index] for row in out.rows if index < len(row)]
        nested = infer_nested(values)
        if nested:
            out.nested[name] = nested
    return out

# ---------------------------------------------------------------------------
# Previewing a whole statement, rather than one source.

_INSERT = re.compile(
    r"^\s*INSERT\s+INTO\s+(?:`[^`]+`|[\w.]+)\s*(?:\([^)]*\))?\s*(?=SELECT|WITH|VALUES)",
    re.I | re.S,
)


def select_of(sql_text: str) -> str:
    """The query half of an INSERT, so it can be run without writing anything.

    Refuses a statement set rather than guessing which of its inserts was meant:
    a preview that silently shows one branch of a fan-out is worse than one that
    says it cannot.
    """
    cleaned = strip_noise(sql_text)
    if re.search(r"\bEXECUTE\s+STATEMENT\s+SET\b", cleaned, re.I):
        raise ValueError(
            "This job writes to more than one sink at once. Preview the statements "
            "one at a time."
        )
    # Matched against the comment-stripped text, because a stored statement
    # usually opens with a paragraph explaining itself. strip_noise preserves
    # length, so offsets still line up with the original and the slice keeps any
    # comments that sit inside the query.
    match = _INSERT.search(cleaned)
    if not match:
        if re.match(r"^\s*(SELECT|WITH)\b", cleaned, re.I):
            return sql_text.strip().rstrip(";")
        raise ValueError(
            "Only an INSERT INTO ... SELECT can be previewed; this statement does "
            "not have a query to run."
        )
    return sql_text[match.end():].strip().rstrip(";")


async def preview_statement(
    gateway: SqlGatewayClient,
    store: SecretStore,
    db: Session,
    sources: list[CatalogEntry],
    sql_text: str,
    limit: int = 20,
    start: str = "earliest",
) -> SampleResult:
    """Runs a job's query and returns the rows it would have written.

    Only the *source* tables are created. The sink is never defined, so nothing
    here can write to Kafka, to a database, or to a light switch -- the preview
    is unable to have a side effect rather than merely choosing not to.
    """
    try:
        query = select_of(sql_text)
    except ValueError as exc:
        return SampleResult(error=str(exc))

    wanted = max(1, min(limit, 100))
    session = await gateway.open_session({"parallelism.default": "1"})
    try:
        for entry in sources:
            # Each source keeps its own name, so the query needs no rewriting, but
            # gets a throwaway consumer group: a preview must not take partitions
            # from the job that owns the real one.
            ddl = build_preview_ddl(entry, entry.name, start)
            await gateway.execute(session, store.resolve(db, ddl))

        result = await gateway.select_rows(
            session, f"SELECT * FROM ({query}) LIMIT {wanted}", wanted
        )
        out = SampleResult(
            columns=list(result.columns), rows=[list(r) for r in result.rows]
        )
    except GatewayError as exc:
        message = store.redact(db, exc.summary)
        if "did not settle" in message:
            message = (
                "The cluster did not start the query in time. It may have no free slots."
            )
        return SampleResult(error=message)
    except ValueError as exc:
        return SampleResult(error=str(exc))
    finally:
        try:
            await gateway.close_session(session)
        except Exception as exc:  # pragma: no cover - cleanup must not mask results
            log.warning("Could not close preview session: %s", exc)

    if not out.rows:
        out.error = (
            "The query produced no rows within the time limit. The sources may be "
            "empty, or nothing may match."
        )
    return out
