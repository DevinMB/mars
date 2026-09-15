"""Drafts a Flink SQL statement from a description.

The model is the least interesting part of this. What makes a draft worth
offering is everything around it:

* **It is told what exists.** The tables the job declares, their columns and
  types, and -- for a source carrying an opaque JSON document -- the field names
  found by sampling a real record. A model inventing column names is the usual
  failure, and it is mostly a failure to be told the names.
* **It is checked before anyone sees it.** The draft goes through the same
  validation as a hand-written statement, and a failure is fed back once for
  repair. A draft that does not compile is reported as such rather than quietly
  handed over.
* **It is never submitted.** The result lands in the editor for a person to read,
  edit and approve. That rule is what makes the feature safe, and it lives here
  rather than in the UI: this module returns text, and has no way to run it.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .ai import AiClient, AiError

log = logging.getLogger(__name__)

SYSTEM = """You write Apache Flink SQL statements and nothing else.

Rules:
- Reply with one SQL statement. No prose, no explanation, no markdown fences.
- Use only the tables and columns listed below. Never invent a name.
- A job reads from sources and writes to a sink: INSERT INTO <sink> SELECT ... FROM <source>.
- The SELECT list must match the sink's columns in order and type. Cast where needed.
- To read a field out of a JSON document held in a STRING column, use
  JSON_VALUE(column, '$.field'). Cast the result if the sink wants a number.
- Flink SQL is not MySQL or Postgres. Do not use LIMIT on an unbounded stream,
  do not ORDER BY a non-time column, and remember a plain Kafka sink cannot
  accept updates from a non-windowed GROUP BY.
- Quote identifiers with backticks when they are reserved words, such as
  `timestamp` or `status`."""


@dataclass
class DraftResult:
    sql: str = ""
    ok: bool = False
    error: str | None = None
    hint: str | None = None
    # How many times the model was asked. Two means the first draft failed to
    # compile and was repaired.
    attempts: int = 0
    notes: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    """Strips what a model adds around a statement, however it was asked not to.

    Fences appear anyway, sometimes labelled ```sql and sometimes not, and a
    reasoning model may emit a <think> block first. Removing them here is more
    reliable than insisting in the prompt.
    """
    out = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I).strip()

    fenced = re.search(r"```(?:sql)?\s*(.+?)```", out, flags=re.S | re.I)
    if fenced:
        out = fenced.group(1)

    lines = [
        ln for ln in out.splitlines()
        if not re.match(r"^\s*(here'?s|this (statement|query)|the following)\b", ln, re.I)
    ]
    out = "\n".join(lines).strip()
    # A single trailing semicolon is idiomatic but the submitter splits on them.
    return out.rstrip().rstrip(";").strip()


def describe_tables(tables: list[dict]) -> str:
    """The catalog, as the model needs to see it.

    Sinks are called out separately from sources because the single most common
    mistake is writing into a table that is not the sink, and a flat list invites
    exactly that.
    """
    lines: list[str] = []
    for kind, label in (("source", "SOURCES (read from these)"),
                        ("sink", "SINKS (write to these)")):
        chosen = [t for t in tables if t.get("kind") == kind]
        if not chosen:
            continue
        lines.append(label + ":")
        for t in chosen:
            columns = ", ".join(
                f"`{c['name']}` {c['type']}" for c in t.get("columns", [])
            ) or "(no columns could be read)"
            lines.append(f"  {t['name']} ({columns})")
            for column, fields in (t.get("document_fields") or {}).items():
                if fields:
                    listed = ", ".join(sorted(fields)[:40])
                    lines.append(
                        f"    `{column}` holds a JSON document with fields: {listed}"
                    )
            lines.append("")
    return "\n".join(lines).strip()


def build_prompt(description: str, tables: list[dict], job_type: str) -> str:
    catalog = describe_tables(tables) or "No tables have been selected for this job."
    kind = (
        "This is a streaming job: it runs continuously over an unbounded input."
        if job_type != "batch"
        else "This is a batch job: it reads a finite input and finishes."
    )
    return (
        f"{catalog}\n\n{kind}\n\n"
        f"Write the statement for this request:\n{description.strip()}"
    )


async def draft_statement(
    client: AiClient,
    description: str,
    tables: list[dict],
    job_type: str,
    validate,
    repair: bool = True,
) -> DraftResult:
    """Drafts, validates, and repairs once if the first attempt does not compile.

    ``validate`` is a coroutine taking SQL and returning ``(ok, error, hint)``.
    Passed in rather than imported so this module cannot submit anything, only
    ask whether something would compile.
    """
    result = DraftResult()

    try:
        raw = await client.complete(build_prompt(description, tables, job_type), SYSTEM)
    except AiError as exc:
        result.error = str(exc)
        return result
    result.attempts = 1
    result.sql = _clean(raw)

    if not result.sql:
        result.error = "The model returned nothing usable."
        return result

    ok, error, hint = await validate(result.sql)
    if ok:
        result.ok = True
        return result

    if not repair:
        result.error, result.hint = error, hint
        return result

    # One repair attempt. The error is the plain-language one the console already
    # produces, which is at least as useful to a model as it is to a person.
    result.notes.append(f"The first draft did not compile: {error}")
    retry = (
        f"{build_prompt(description, tables, job_type)}\n\n"
        f"A previous attempt was:\n{result.sql}\n\n"
        f"It failed to compile with: {error}\n"
        f"{('Hint: ' + hint) if hint else ''}\n"
        f"Correct it. Reply with the corrected statement only."
    )
    try:
        repaired = _clean(await client.complete(retry, SYSTEM))
    except AiError as exc:
        result.error, result.hint = error, hint
        result.notes.append(f"The repair attempt failed: {exc}")
        return result

    result.attempts = 2
    if repaired:
        result.sql = repaired
        ok, error, hint = await validate(result.sql)

    result.ok = ok
    result.error = None if ok else error
    result.hint = None if ok else hint
    return result
