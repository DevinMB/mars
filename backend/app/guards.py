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

    if connector == "kafka" and kind == "sink":
        guarantee = opts.get("sink.delivery-guarantee", "at-least-once")
        acks = opts.get("properties.acks")

        # Flink accepts acks=0 without complaint. The producer then never learns
        # whether a record arrived, so flushing at a checkpoint proves nothing and
        # the delivery guarantee above it is decorative.
        if acks == "0" and guarantee != "none":
            out.append(
                Warning_(
                    "danger",
                    "kafka_acks_zero",
                    f"Acknowledgements are set to 0, so the producer never learns "
                    f"whether a record arrived. That cancels the '{guarantee}' "
                    f"guarantee set on this sink: records will be lost on any broker "
                    f"hiccup and nothing will report it. Use 'all'.",
                )
            )
        elif acks == "1" and guarantee == "exactly-once":
            out.append(
                Warning_(
                    "warning",
                    "kafka_acks_one",
                    "Only the partition leader has to confirm a write. A transaction "
                    "can then commit records that no replica holds, and they are lost "
                    "if that broker fails before they replicate. Use 'all' with "
                    "exactly-once.",
                )
            )

        if guarantee == "exactly-once" and not opts.get("sink.transactional-id-prefix"):
            out.append(
                Warning_(
                    "danger",
                    "kafka_no_txn_prefix",
                    "Exactly-once needs a transactional id prefix, and this sink has "
                    "none. The job will be rejected when it is submitted.",
                )
            )

        # Brokers default transaction.max.timeout.ms to 15 minutes and reject
        # anything longer, at submission rather than at authoring time.
        timeout = opts.get("properties.transaction.timeout.ms")
        if timeout and timeout.isdigit() and int(timeout) > 900_000:
            out.append(
                Warning_(
                    "warning",
                    "kafka_txn_timeout",
                    f"A transaction timeout of {timeout}ms is above the broker default "
                    f"limit of 900000ms (transaction.max.timeout.ms). Unless that limit "
                    f"has been raised, the broker will refuse this producer.",
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

    # A transactional producer is fenced by its id: when two jobs share a prefix,
    # each one starting up aborts the other's open transactions. Both stall, and
    # neither reports anything more specific than transactions timing out.
    prefixes = {
        parse_options(e.sql_text).get("sink.transactional-id-prefix")
        for e in sinks.values()
        if e.connector == "kafka"
    } - {None, ""}
    if prefixes:
        for other in db.query(Job).filter(Job.id != job.id).all():
            other_refs = _refs(other)
            if not other_refs:
                continue
            for e in (
                db.query(CatalogEntry)
                .filter(CatalogEntry.name.in_(other_refs), CatalogEntry.kind == "sink")
                .all()
            ):
                if e.connector != "kafka":
                    continue
                prefix = parse_options(e.sql_text).get("sink.transactional-id-prefix")
                if prefix and prefix in prefixes:
                    out.append(
                        Warning_(
                            "danger",
                            "kafka_shared_txn_prefix",
                            f"Job '{other.name}' uses the same transactional id prefix "
                            f"'{prefix}'. Kafka fences producers by that id, so the two "
                            f"jobs will abort each other's transactions and neither will "
                            f"make progress. Give each job its own prefix.",
                        )
                    )

    # Reading a topic that an exactly-once producer writes, without asking for
    # committed records only, means seeing writes from transactions that were
    # later aborted -- records that, as far as the producer is concerned, never
    # happened.
    transactional_topics: set[str] = set()
    for e in db.query(CatalogEntry).filter(CatalogEntry.kind == "sink").all():
        if e.connector != "kafka":
            continue
        o = parse_options(e.sql_text)
        if o.get("sink.delivery-guarantee") == "exactly-once" and o.get("topic"):
            transactional_topics.add(o["topic"])

    for name, e in sources.items():
        if e.connector != "kafka":
            continue
        o = parse_options(e.sql_text)
        topic = o.get("topic")
        if (
            topic in transactional_topics
            and o.get("properties.isolation.level") != "read_committed"
        ):
            out.append(
                Warning_(
                    "warning",
                    "kafka_uncommitted_read",
                    f"'{name}' reads topic '{topic}', which is written by an "
                    f"exactly-once producer, but does not set isolation level to "
                    f"read_committed. It will see records from transactions that were "
                    f"later aborted.",
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

# The name may be backtick-quoted; the closing backtick must not be swept into
# the type, which produced DDL like "`id` ` BIGINT" when this was rebuilt.
_COLUMN_LINE = re.compile(
    r"^\s*(?:`(?P<quoted>[^`]+)`|(?P<name>[A-Za-z_][\w$]*))\s+(?P<rest>[A-Za-z].*)$",
    re.S,
)
_RESERVED = {"primary", "watermark", "constraint", "unique", "partitioned", "with"}


def strip_noise(sql_text: str) -> str:
    """Removes comments and blanks string literals, keeping length and layout.

    Necessary before counting brackets. A catalog entry usually opens with a
    paragraph of explanation, and prose contains parentheses -- one entry here
    begins "produced by stack 4 (and by sit_sessionize in parallel)", which a
    naive scan reads as the start of the column list and yields a column called
    "and". Another says "(stack 9)", which unbalances the depth count and yields
    nothing at all.
    """
    out = []
    i = 0
    n = len(sql_text)
    while i < n:
        ch = sql_text[i]
        nxt = sql_text[i + 1] if i + 1 < n else ""
        if ch == "-" and nxt == "-":
            while i < n and sql_text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if ch == "/" and nxt == "*":
            while i < n and not (sql_text[i] == "*" and sql_text[i + 1 : i + 2] == "/"):
                out.append(" " if sql_text[i] != "\n" else "\n")
                i += 1
            out.append("  ")
            i += 2
            continue
        if ch == "'":
            out.append(" ")
            i += 1
            while i < n:
                if sql_text[i] == "'" and sql_text[i + 1 : i + 2] == "'":
                    out.append("  ")
                    i += 2
                    continue
                if sql_text[i] == "'":
                    out.append(" ")
                    i += 1
                    break
                out.append("\n" if sql_text[i] == "\n" else " ")
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def column_names(sql_text: str) -> list[str]:
    """The column names declared by a CREATE TABLE.

    Used to suggest a correction when someone misspells one, and to show the
    available columns while a job is being written.
    """
    return [name for name, _ in columns_of(sql_text)]


def columns_of(sql_text: str) -> list[tuple[str, str]]:
    """The (name, type) pairs declared by a CREATE TABLE, in declared order."""
    sql_text = strip_noise(sql_text)
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

    columns: list[tuple[str, str]] = []
    for part in out:
        m = _COLUMN_LINE.match(part.strip())
        if not m:
            continue
        name = m.group("quoted") or m.group("name")
        if not name or name.lower() in _RESERVED:
            continue
        # Whatever follows is the type, possibly with a METADATA or
        # computed-column clause; collapse it to one line.
        columns.append((name, " ".join(m.group("rest").split())))
    return columns
