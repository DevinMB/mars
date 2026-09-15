"""Pre-flight checks shown before a job runs.

These exist because the ways a stream job damages something are rarely syntax
errors -- the SQL compiles perfectly and then quietly breaks something else.

The checks are advisory by design. MARS shows them and lets an informed user
proceed, because every one of them has a legitimate exception: you may genuinely
want two jobs writing the same topic, and you may genuinely want to adopt an
existing consumer group during a cutover. What MARS must not do is let someone
hit that by accident.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .models import CatalogEntry, Job

# Pulls 'key' = 'value' pairs out of a WITH clause without a full SQL parse.
_OPTION = re.compile(r"'([A-Za-z0-9_.\-]+)'\s*=\s*'((?:[^']|'')*)'")
_TABLE_NAME = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([A-Za-z_][\w$]*)`?", re.I)

# Group ids MARS creates are prefixed so they can never collide with a consumer
# that already exists on the broker.
GROUP_PREFIX = "mars-"


@dataclass
class Warning_:
    level: str  # "warning" | "danger"
    code: str
    message: str


def parse_options(sql_text: str) -> dict[str, str]:
    """Extracts the WITH options from a CREATE TABLE."""
    body = sql_text.split("WITH", 1)[-1]
    return {k: v.replace("''", "'") for k, v in _OPTION.findall(body)}


def table_name(sql_text: str) -> str | None:
    m = _TABLE_NAME.search(sql_text)
    return m.group(1) if m else None


def check_catalog_entry(entry_sql: str, kind: str, connector: str) -> list[Warning_]:
    """Checks one source or sink definition in isolation."""
    out: list[Warning_] = []
    opts = parse_options(entry_sql)

    if connector == "kafka" and kind == "source":
        group = opts.get("properties.group.id", "")
        if not group:
            out.append(
                Warning_(
                    "warning",
                    "kafka_no_group",
                    "No consumer group is set. Flink will generate one, so this job "
                    "cannot resume where it left off after a restart.",
                )
            )
        elif not group.startswith(GROUP_PREFIX):
            out.append(
                Warning_(
                    "danger",
                    "kafka_group_collision",
                    f"Consumer group '{group}' does not start with '{GROUP_PREFIX}'. If an "
                    f"application outside MARS already uses this group, Kafka will give the "
                    f"partition to only one of them and the other will silently stop "
                    f"receiving records. Use '{GROUP_PREFIX}{group}' unless you are "
                    f"deliberately taking over an existing group.",
                )
            )

    if connector == "couchdb" and kind == "sink":
        mode = opts.get("id.mode", "kafka_key")
        if mode == "auto":
            out.append(
                Warning_(
                    "warning",
                    "couchdb_auto_id",
                    "Document ids are server-generated, so this sink is not idempotent: "
                    "a replay or a restart from a checkpoint writes duplicate documents. "
                    "Any other id strategy makes replays safe.",
                )
            )

    return out


def check_job(db: Session, job: Job) -> list[Warning_]:
    """Checks a job against its catalog entries and every other stored job."""
    out: list[Warning_] = []

    refs = _refs(job)
    if not refs:
        return out

    entries = {
        e.name: e for e in db.query(CatalogEntry).filter(CatalogEntry.name.in_(refs)).all()
    }

    sources = {n: e for n, e in entries.items() if e.kind == "source"}
    sinks = {n: e for n, e in entries.items() if e.kind == "sink"}

    for entry in entries.values():
        out.extend(check_catalog_entry(entry.sql_text, entry.kind, entry.connector))

    # A job reading and writing the same Kafka topic feeds itself forever.
    source_topics = {
        parse_options(e.sql_text).get("topic")
        for e in sources.values()
        if e.connector == "kafka"
    } - {None}
    sink_topics = {
        parse_options(e.sql_text).get("topic")
        for e in sinks.values()
        if e.connector == "kafka"
    } - {None}

    for topic in source_topics & sink_topics:
        out.append(
            Warning_(
                "danger",
                "topic_loop",
                f"This job reads and writes topic '{topic}'. Every record it produces "
                f"will be read back in, which grows without bound.",
            )
        )

    # Two jobs producing into one topic interleave. Kafka has no upsert, so the
    # result is two copies of every record for anything downstream.
    if sink_topics:
        for other in db.query(Job).filter(Job.id != job.id).all():
            other_refs = _refs(other)
            if not other_refs:
                continue
            others = (
                db.query(CatalogEntry)
                .filter(CatalogEntry.name.in_(other_refs), CatalogEntry.kind == "sink")
                .all()
            )
            for e in others:
                if e.connector != "kafka":
                    continue
                topic = parse_options(e.sql_text).get("topic")
                if topic and topic in sink_topics:
                    out.append(
                        Warning_(
                            "warning",
                            "shared_output_topic",
                            f"Job '{other.name}' also writes to topic '{topic}'. Kafka "
                            f"appends rather than upserts, so consumers of that topic will "
                            f"see every record twice.",
                        )
                    )

    # Two sinks writing the same CouchDB database is fine when ids are
    # deterministic, and silently doubling when they are not.
    couch_targets: dict[tuple[str, str], list[str]] = {}
    for name, e in sinks.items():
        if e.connector != "couchdb":
            continue
        o = parse_options(e.sql_text)
        key = (o.get("url", ""), o.get("db", ""))
        couch_targets.setdefault(key, []).append(name)

    for (url, dbname), names in couch_targets.items():
        if len(names) > 1:
            out.append(
                Warning_(
                    "warning",
                    "shared_couchdb_target",
                    f"{len(names)} sinks in this job write to database '{dbname}'. That is "
                    f"safe only while both compute the same document id; otherwise they "
                    f"overwrite each other's documents.",
                )
            )

    return _dedupe(out)


def _refs(job: Job) -> list[str]:
    try:
        v = json.loads(job.catalog_refs or "[]")
        return [str(x) for x in v] if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


def _dedupe(warnings: list[Warning_]) -> list[Warning_]:
    seen: set[tuple[str, str]] = set()
    out: list[Warning_] = []
    for w in warnings:
        key = (w.code, w.message)
        if key not in seen:
            seen.add(key)
            out.append(w)
    # Danger first: the console shows these in order.
    return sorted(out, key=lambda w: 0 if w.level == "danger" else 1)

_COLUMN_LINE = re.compile(r"^\s*`?(?P<name>[A-Za-z_][\w$]*)`?\s+[A-Za-z]")
_RESERVED = {"primary", "watermark", "constraint", "unique", "partitioned", "with"}


def column_names(sql_text: str) -> list[str]:
    """The column names declared by a CREATE TABLE.

    Only used to suggest a correction when someone misspells one, so a definition
    this cannot parse costs nothing -- it just means no suggestion.
    """
    open_paren = sql_text.find("(")
    if open_paren < 0:
        return []
    depth = 0
    end = -1
    for i, ch in enumerate(sql_text[open_paren:], start=open_paren):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return []

    out: list[str] = []
    depth = 0
    current = ""
    for ch in sql_text[open_paren + 1 : end]:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(current)
            current = ""
        else:
            current += ch
    out.append(current)

    names = []
    for part in out:
        m = _COLUMN_LINE.match(part)
        if m and m.group("name").lower() not in _RESERVED:
            names.append(m.group("name"))
    return names
