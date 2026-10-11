"""Which tables each job reads and writes, and what each table points at.

A catalog entry used to be fixed as a source or a sink. That role is really a
property of how a job uses the table: one job writes a Kafka topic that another
reads. So it is derived here instead, from the job itself.

Two ways, best first:

* **Flink's plan.** Validating a job runs EXPLAIN, and the plan names every table
  read (TableSourceScan, LookupJoin) and written (Sink). Exact for any SQL Flink
  accepts. Kept on the job with a fingerprint of the SQL it came from, and used
  only while that SQL is unchanged.
* **The SQL text.** Tables after INSERT INTO are written; the job's other catalog
  tables are read. Used when there is no current plan, e.g. Flink was unreachable.
  On the home pipeline it matched the stored source/sink role for 21 of 21 entries.

What a table points at ("resource") is what groups entries: every table on Kafka
topic T is the same topic, however many entries describe it.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .guards import parse_options, strip_noise
from .models import CatalogEntry, Job

# INSERT INTO|OVERWRITE [catalog.][db.]name, with or without backticks.
_INSERT = re.compile(
    r"\bINSERT\s+(?:INTO|OVERWRITE)\s+(?:TABLE\s+)?((?:`[^`]+`|[\w$]+)(?:\s*\.\s*(?:`[^`]+`|[\w$]+))*)",
    re.I,
)
_PLAN_SINK = re.compile(r"\bSink\(table=\[([^\]]+)\]")
_PLAN_SCAN = re.compile(r"\bTableSourceScan\(table=\[\[([^\]]+)\]\]")
_PLAN_LOOKUP = re.compile(r"\bLookupJoin\(table=\[([^\]]+)\]")


def _last_part(qualified: str) -> str:
    """`cat`.`db`.`t` or cat.db.t or "cat, db, t" -> t"""
    part = re.split(r"\s*[.,]\s*", qualified.strip())[-1]
    return part.strip("` ")


@dataclass
class Usage:
    reads: set[str] = field(default_factory=set)
    writes: set[str] = field(default_factory=set)
    source: str = "sql"  # "plan" or "sql"


def refs_of(job: Job) -> list[str]:
    try:
        refs = json.loads(job.catalog_refs or "[]")
    except json.JSONDecodeError:
        return []
    return [str(r) for r in refs] if isinstance(refs, list) else []


def fingerprint(job: Job) -> str:
    """What a stored plan was derived from: the job's SQL and its tables."""
    return hashlib.sha256(f"{job.sql_text}\0{job.catalog_refs}".encode()).hexdigest()


def usage_from_sql(sql_text: str, refs: list[str]) -> Usage:
    text = strip_noise(sql_text)
    written = {_last_part(m.group(1)) for m in _INSERT.finditer(text)}
    writes = {r for r in refs if r in written}
    reads = set()
    for r in refs:
        if r not in writes:
            reads.add(r)
        elif re.search(rf"\b(?:FROM|JOIN)\s+`?{re.escape(r)}`?\b", text, re.I):
            reads.add(r)  # read and written by the same job: a loop the checks flag
    return Usage(reads=reads, writes=writes, source="sql")


def usage_from_plan(plan: str, refs: list[str]) -> Usage:
    """Tables named in an EXPLAIN plan, limited to the job's catalog tables."""
    writes = {_last_part(m) for m in _PLAN_SINK.findall(plan)}
    reads = {_last_part(m) for m in _PLAN_SCAN.findall(plan)}
    reads |= {_last_part(m) for m in _PLAN_LOOKUP.findall(plan)}
    known = set(refs)
    return Usage(reads=reads & known, writes=writes & known, source="plan")


def job_usage(job: Job) -> Usage:
    """The plan's answer while it matches the job's SQL; otherwise the SQL's."""
    if job.tables_from == "plan" and job.tables_key == fingerprint(job):
        try:
            return Usage(reads=set(json.loads(job.tables_read or "[]")),
                         writes=set(json.loads(job.tables_written or "[]")), source="plan")
        except json.JSONDecodeError:
            pass
    return usage_from_sql(job.sql_text or "", refs_of(job))


def record_plan(job: Job, plans: list[str]) -> Usage:
    """Keeps what Flink's plan says, tied to the SQL it was made from."""
    refs = refs_of(job)
    usage = Usage(source="plan")
    for plan in plans:
        u = usage_from_plan(plan, refs)
        usage.reads |= u.reads
        usage.writes |= u.writes
    job.tables_read = json.dumps(sorted(usage.reads))
    job.tables_written = json.dumps(sorted(usage.writes))
    job.tables_from = "plan"
    job.tables_key = fingerprint(job)
    return usage


# Plans from the editor's live check, by fingerprint, so saving the same SQL
# moments later keeps the plan instead of falling back to reading the SQL.
_RECENT_PLANS: dict[str, list[str]] = {}
_RECENT_LIMIT = 200


def remember_plans(job: Job, plans: list[str]) -> None:
    _RECENT_PLANS.pop(fingerprint(job), None)
    _RECENT_PLANS[fingerprint(job)] = plans
    while len(_RECENT_PLANS) > _RECENT_LIMIT:
        _RECENT_PLANS.pop(next(iter(_RECENT_PLANS)))


def recall_plans(job: Job) -> list[str] | None:
    return _RECENT_PLANS.get(fingerprint(job))


@dataclass
class Resource:
    """What a table points at. Tables with the same key are the same thing."""
    key: str
    kind: str  # e.g. "kafka topic", "couchdb database"; the connector for unknowns
    label: str


# For each connector: the option naming the server (part of the identity, since
# two clusters can share a topic or database name), the option naming the thing
# itself, and what to call it.
_IDENTITY: dict[str, tuple[str | None, str, str]] = {
    "kafka": ("properties.bootstrap.servers", "topic", "kafka topic"),
    "upsert-kafka": ("properties.bootstrap.servers", "topic", "kafka topic"),
    "couchdb": ("url", "db", "couchdb database"),
    "filesystem": (None, "path", "path"),
    "jdbc": ("url", "table-name", "database table"),
}


def resource_of(entry: CatalogEntry, registry=None) -> Resource:
    """registry: a ConnectorRegistry, whose manifests can declare an identity."""
    o = parse_options(entry.sql_text)
    ident = _IDENTITY.get(entry.connector)
    declared = registry.get(entry.connector) if registry is not None else None
    if declared is not None and declared.identity:
        d = declared.identity
        ident = (d.get("server"), d["name"], d["label"])
    if ident and o.get(ident[1]):
        server_opt, name_opt, kind = ident
        server = o.get(server_opt, "") if server_opt else ""
        # Kafka and upsert-kafka on the same topic are the same topic.
        family = "kafka" if entry.connector in ("kafka", "upsert-kafka") else entry.connector
        return Resource(key=f"{family}:{server}/{o[name_opt]}", kind=kind, label=o[name_opt])
    # Unknown connectors are their own resource: correct, just ungrouped.
    return Resource(key=f"table:{entry.name}", kind=entry.connector, label=entry.name)


def role_hint(entry: CatalogEntry, registry=None) -> str:
    """'source', 'sink' or 'table' (either), for something with no job yet, like
    an AI draft: an older entry's stored role, else what its connector allows."""
    if entry.kind in ("source", "sink"):
        return entry.kind
    connector = registry.get(entry.connector) if registry is not None else None
    kinds = set(connector.kinds) if connector else set()
    if kinds == {"source"}:
        return "source"
    if kinds == {"sink"}:
        return "sink"
    return "table"


@dataclass
class TableUsage:
    read_by: list[str] = field(default_factory=list)
    written_by: list[str] = field(default_factory=list)


def catalog_usage(db: Session) -> dict[str, TableUsage]:
    """For every catalog entry, the jobs that read and write it."""
    out = {e.name: TableUsage() for e in db.query(CatalogEntry)}
    for job in db.query(Job).order_by(Job.name):
        u = job_usage(job)
        for name in u.reads:
            if name in out:
                out[name].read_by.append(job.name)
        for name in u.writes:
            if name in out:
                out[name].written_by.append(job.name)
    return out
