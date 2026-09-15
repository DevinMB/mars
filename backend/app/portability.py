"""Export and import a MARS installation's definitions as YAML.

Two problems, one mechanism.

The first is recovery. Everything MARS knows lives in one SQLite file in one
Docker volume: every catalog entry, job, schedule and target. Lose the volume and
there is no way back. An export is the copy that lives somewhere else.

The second is review. Teams want definitions in version control, diffed in a pull
request rather than typed into a form on a production console.

**Secret values are never exported.** An export is a file people mail around and
commit to repositories; a credential in one is a credential leaked. What is
exported is the ``${secret:name}`` reference already present in the DDL, and a
list of the names an import will need. Restoring an installation therefore means
restoring this file *and* re-entering the secrets -- which is stated plainly in
the export itself rather than discovered later.

Nor does this carry run history, users or password hashes. Those are operational
state, not definitions, and belong to a volume backup. The export says so.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import yaml
from sqlalchemy.orm import Session

from .guards import parse_options
from .models import CatalogEntry, Job, Schedule, Target
from .secrets import SecretStore

log = logging.getLogger(__name__)

# Bumped when the shape changes in a way an older MARS could not read.
FORMAT_VERSION = 1


@dataclass
class ImportOutcome:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Secrets the imported definitions reference but this installation lacks.
    missing_secrets: list[str] = field(default_factory=list)
    dry_run: bool = True

    @property
    def ok(self) -> bool:
        return not self.errors


def _refs(job: Job) -> list[str]:
    try:
        value = json.loads(job.catalog_refs or "[]")
        return [str(v) for v in value] if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def referenced_secrets(db: Session, store: SecretStore) -> list[str]:
    """Every secret name the definitions mention, whether or not it exists."""
    names: set[str] = set()
    for entry in db.query(CatalogEntry).all():
        names |= store.referenced_names(entry.sql_text)
    for job in db.query(Job).all():
        names |= store.referenced_names(job.sql_text)
    return sorted(names)


def export_all(db: Session, store: SecretStore) -> dict[str, Any]:
    """The whole installation's definitions, as plain data."""
    catalog = [
        {
            "name": e.name,
            "kind": e.kind,
            "connector": e.connector,
            "description": e.description,
            "sql": e.sql_text,
        }
        for e in db.query(CatalogEntry).order_by(CatalogEntry.name).all()
    ]

    jobs = []
    for job in db.query(Job).order_by(Job.name).all():
        item: dict[str, Any] = {
            "name": job.name,
            "description": job.description,
            "type": job.job_type,
            "enabled": job.enabled,
            "uses": _refs(job),
            "sql": job.sql_text,
        }
        if job.target_name:
            item["target"] = job.target_name
        schedule = job.schedule
        if schedule:
            item["schedule"] = {
                "mode": schedule.mode,
                "cron": schedule.cron_expr,
                "timezone": schedule.timezone_name,
                "enabled": schedule.enabled,
            }
        jobs.append(item)

    targets = [
        {
            "name": t.name,
            "description": t.description,
            "flink_rest_url": t.flink_rest_url,
            "gateway_url": t.gateway_url,
            "ui_url": t.ui_url,
            "default": t.is_default,
            "enabled": t.enabled,
        }
        for t in db.query(Target).order_by(Target.name).all()
    ]

    secrets = referenced_secrets(db, store)

    return {
        "format": FORMAT_VERSION,
        # Said in the file, because the file is what someone will be holding when
        # they try to restore from it.
        "note": (
            "Definitions only. Secret VALUES are deliberately absent -- restoring "
            "this file also means re-entering the secrets listed under "
            "secrets_required. Run history, user accounts and the encryption key "
            "are not here either; those need a backup of the console's data volume."
        ),
        "secrets_required": secrets,
        "targets": targets,
        "catalog": catalog,
        "jobs": jobs,
    }


class _Dumper(yaml.SafeDumper):
    """Emits multi-line strings as block literals.

    Left to itself PyYAML writes a SQL statement as one double-quoted scalar with
    escaped newlines, which is valid and unreadable: every change to a statement
    shows up as one enormous modified line. Half the point of exporting YAML is
    reviewing it in a diff, so multi-line strings are written as `|` blocks and
    diff a line at a time.
    """


def _literal_str(dumper: yaml.SafeDumper, value: str):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _literal_str)


def to_yaml(payload: dict[str, Any]) -> str:
    return yaml.dump(
        payload, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100
    )


def parse(text: str) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"This is not valid YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("An export is a mapping with 'catalog' and 'jobs' keys.")
    version = payload.get("format")
    if version is not None and int(version) > FORMAT_VERSION:
        raise ValueError(
            f"This export is format {version}; this MARS understands {FORMAT_VERSION}. "
            f"Upgrade before importing it."
        )
    return payload


def import_all(
    db: Session,
    store: SecretStore,
    payload: dict[str, Any],
    dry_run: bool = True,
    replace: bool = False,
) -> ImportOutcome:
    """Applies an export.

    Defaults to a dry run on purpose: this writes over definitions that jobs are
    running from, and seeing the list first is the difference between an import
    and an accident. ``replace`` overwrites entries that already exist; without
    it they are left alone and reported as skipped, so importing into a populated
    installation is additive by default.
    """
    outcome = ImportOutcome(dry_run=dry_run)

    have_secrets = set(store.names(db))
    wanted = set(payload.get("secrets_required") or [])
    for entry in payload.get("catalog") or []:
        wanted |= store.referenced_names(entry.get("sql") or "")
    for job in payload.get("jobs") or []:
        wanted |= store.referenced_names(job.get("sql") or "")
    outcome.missing_secrets = sorted(wanted - have_secrets)

    # Catalog first: a job that references an entry cannot be validated before it
    # exists, and the import order is the same order the console enforces.
    for item in payload.get("catalog") or []:
        name = item.get("name")
        if not name or not item.get("sql"):
            outcome.errors.append(f"catalog entry without a name or sql: {item!r}"[:200])
            continue
        existing = db.query(CatalogEntry).filter(CatalogEntry.name == name).one_or_none()
        if existing is None:
            outcome.created.append(f"catalog/{name}")
            if not dry_run:
                db.add(CatalogEntry(
                    name=name,
                    kind=item.get("kind", "source"),
                    connector=item.get("connector", ""),
                    description=item.get("description"),
                    sql_text=item["sql"],
                    options_json=json.dumps(_options_of(item)),
                ))
        elif not replace:
            outcome.skipped.append(f"catalog/{name}")
        elif existing.sql_text == item["sql"] and existing.description == item.get("description"):
            outcome.unchanged.append(f"catalog/{name}")
        else:
            outcome.updated.append(f"catalog/{name}")
            if not dry_run:
                existing.kind = item.get("kind", existing.kind)
                existing.connector = item.get("connector", existing.connector)
                existing.description = item.get("description")
                existing.sql_text = item["sql"]
                existing.options_json = json.dumps(_options_of(item))

    if not dry_run:
        db.flush()

    known = {e.name for e in db.query(CatalogEntry).all()} | {
        i.get("name") for i in (payload.get("catalog") or [])
    }

    for item in payload.get("jobs") or []:
        name = item.get("name")
        if not name or not item.get("sql"):
            outcome.errors.append(f"job without a name or sql: {item!r}"[:200])
            continue

        uses = [str(u) for u in (item.get("uses") or [])]
        unknown = [u for u in uses if u not in known]
        if unknown:
            # Importing a job that names tables nothing provides produces a job
            # that cannot run. Better to refuse it and say which.
            outcome.errors.append(
                f"job/{name} uses catalog entries that are neither in this export "
                f"nor already here: {', '.join(unknown)}"
            )
            continue

        existing = db.query(Job).filter(Job.name == name).one_or_none()
        if existing is None:
            outcome.created.append(f"job/{name}")
            if not dry_run:
                job = Job(
                    name=name,
                    description=item.get("description"),
                    job_type=item.get("type", "streaming"),
                    sql_text=item["sql"],
                    catalog_refs=json.dumps(uses),
                    enabled=bool(item.get("enabled", True)),
                    target_name=item.get("target") or None,
                )
                db.add(job)
                db.flush()
                _apply_schedule(db, job, item.get("schedule"))
        elif not replace:
            outcome.skipped.append(f"job/{name}")
        elif existing.sql_text == item["sql"] and _refs(existing) == uses:
            outcome.unchanged.append(f"job/{name}")
        else:
            outcome.updated.append(f"job/{name}")
            if not dry_run:
                existing.description = item.get("description")
                existing.job_type = item.get("type", existing.job_type)
                existing.sql_text = item["sql"]
                existing.catalog_refs = json.dumps(uses)
                existing.target_name = item.get("target") or None
                existing.version += 1
                _apply_schedule(db, existing, item.get("schedule"))

    if dry_run:
        db.rollback()
    else:
        db.commit()
    return outcome


def _options_of(item: dict[str, Any]) -> dict[str, str]:
    """Form values for the imported entry, read back out of its DDL.

    An export carries the DDL because that is the definition; the form values are
    a convenience derived from it. Deriving them here means an imported entry
    opens in the editor with its fields filled in rather than blank.
    """
    options = parse_options(item.get("sql") or "")
    options.pop("connector", None)
    return options


def _apply_schedule(db: Session, job: Job, spec: dict[str, Any] | None) -> None:
    existing = job.schedule
    if spec is None:
        if existing is not None:
            db.delete(existing)
        return
    if existing is None:
        existing = Schedule(job_id=job.id)
        db.add(existing)
    existing.mode = spec.get("mode", "supervisor")
    existing.cron_expr = spec.get("cron")
    existing.timezone_name = spec.get("timezone", "UTC")
    existing.enabled = bool(spec.get("enabled", True))
