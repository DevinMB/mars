"""The restore drill: proving backups can actually be restored, on a schedule.

Off unless MARS_RESTORE_DRILL is true. When on, it runs on
MARS_RESTORE_DRILL_SCHEDULE (quarterly by default) and records its result in
/data/restore-drill.json, which /metrics publishes so any monitoring can alert on
a failure.

What it restores: the newest archive in the backups directory (mounted at
/backups), the way it would be restored for real. With no archives there, a fresh
snapshot of the live database instead, which proves the data can be backed up and
read back but not that the backups you keep can.

It runs inside the console, against copies in a temporary directory, with no
network side effects. It cannot start a second console to restore into: the
console deliberately has no Docker access. So instead of migrating the copy it
checks that the copy's schema is one this release can upgrade from, and it reads
the copy with plain SQL rather than the current models.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import tarfile
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from alembic.script import ScriptDirectory
from cryptography.fernet import Fernet, InvalidToken
from croniter import croniter

from .db import session_scope
from .migrations import _config
from .models import Job, RunState
from .settings import settings

log = logging.getLogger(__name__)

ARCHIVE_PATTERNS = ("*.tgz", "*.tar.gz")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class DrillResult:
    ran_at: str
    source: str
    passed: bool
    checks: list[Check] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def result_path() -> Path:
    return settings().data_dir / "restore-drill.json"


def last_result() -> DrillResult | None:
    try:
        raw = json.loads(result_path().read_text())
    except (OSError, ValueError):
        return None
    return DrillResult(
        ran_at=raw["ran_at"], source=raw["source"], passed=raw["passed"],
        checks=[Check(**c) for c in raw.get("checks", [])],
    )


def is_due(now: datetime) -> bool:
    """Due when the schedule has fired since the last run (or since never)."""
    s = settings()
    if not s.restore_drill:
        return False
    last = last_result()
    if last is None:
        return True
    since = datetime.fromisoformat(last.ran_at)
    try:
        nxt = croniter(s.restore_drill_schedule, since).get_next(datetime)
    except (ValueError, KeyError):
        log.error("MARS_RESTORE_DRILL_SCHEDULE is not a valid cron expression: %s",
                  s.restore_drill_schedule)
        return False
    return nxt <= now


def _newest_archive(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None
    found = [p for pattern in ARCHIVE_PATTERNS for p in directory.glob(pattern) if p.is_file()]
    return max(found, key=lambda p: p.stat().st_mtime, default=None)


def _snapshot(into: Path) -> None:
    """A consistent copy of the live database and its key, as a backup would hold."""
    s = settings()
    source = sqlite3.connect(s.data_dir / "mars.db")
    target = sqlite3.connect(into / "mars.db")
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    (into / s.secret_key_file).write_bytes((s.data_dir / s.secret_key_file).read_bytes())


def _contents(db_file: Path) -> dict:
    conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        q = lambda sql: conn.execute(sql).fetchall()  # noqa: E731
        return {
            "schema": q("select version_num from alembic_version")[0][0],
            "jobs": sorted(r[0] for r in q("select name from jobs")),
            "catalog_entries": q("select count(*) from catalog_entries")[0][0],
            "users": q("select count(*) from users")[0][0],
            "secrets": q("select name, ciphertext from secrets"),
        }
    finally:
        conn.close()


def _restore_point_paths() -> list[tuple[str, str]]:
    with session_scope() as db:
        out = []
        for job in db.query(Job).order_by(Job.name):
            latest = job.runs[0] if job.runs else None
            point = job.restore_point
            if latest is not None and latest.state == RunState.RUNNING.value and point:
                out.append((job.name, point.path))
        return out


def run(now: datetime | None = None) -> DrillResult:
    now = now or datetime.now(timezone.utc)
    s = settings()
    checks: list[Check] = []

    def check(name: str, ok: bool, detail: str = "") -> bool:
        checks.append(Check(name, bool(ok), detail))
        return bool(ok)

    archive = _newest_archive(Path(s.restore_drill_backups_dir))
    source = f"archive {archive.name}" if archive else "snapshot of the live database"

    with tempfile.TemporaryDirectory(prefix="mars-drill-") as tmp:
        work = Path(tmp)
        try:
            if archive:
                with tarfile.open(archive) as tar:
                    tar.extractall(work, filter="data")
            else:
                _snapshot(work)
        except Exception as exc:  # an unreadable archive is exactly what this is for
            check("backup can be read", False, str(exc)[:200])
            return _finish(now, source, checks)
        check("backup can be read", True)

        db_file, key_file = work / "mars.db", work / s.secret_key_file
        if not check("backup holds the database and its key",
                     db_file.is_file() and key_file.is_file(),
                     ", ".join(sorted(p.name for p in work.iterdir()))):
            return _finish(now, source, checks)

        try:
            restored = _contents(db_file)
            live = _contents(s.data_dir / "mars.db")
        except Exception as exc:
            check("restored database opens", False, str(exc)[:200])
            return _finish(now, source, checks)
        check("restored database opens", True)

        known = {r.revision for r in ScriptDirectory.from_config(_config()).walk_revisions()}
        check("schema is one this release can upgrade from",
              restored["schema"] in known, restored["schema"])
        check("same jobs as live", restored["jobs"] == live["jobs"],
              f"{len(restored['jobs'])} restored, {len(live['jobs'])} live")
        check("same catalog entries as live",
              restored["catalog_entries"] == live["catalog_entries"],
              f"{restored['catalog_entries']} restored, {live['catalog_entries']} live")
        check("same users as live", restored["users"] == live["users"],
              f"{restored['users']} restored, {live['users']} live")

        fernet = Fernet(key_file.read_bytes().strip())
        failing = []
        for name, ciphertext in restored["secrets"]:
            try:
                fernet.decrypt(ciphertext.encode())
            except (InvalidToken, ValueError):
                failing.append(name)
        check("every secret decrypts with the backed-up key", not failing,
              f"{len(restored['secrets']) - len(failing)}/{len(restored['secrets'])}"
              + (f"; failing: {', '.join(failing)}" if failing else ""))

    state_dir = Path(s.flink_state_dir)
    points = _restore_point_paths()
    if state_dir.is_dir():
        missing = [
            name for name, path in points
            if not (state_dir / path.split("/flink-state/", 1)[-1] / "_metadata").is_file()
        ]
        check("every running job's restore point is on disk", not missing,
              f"{len(points) - len(missing)}/{len(points)}"
              + (f"; missing: {', '.join(missing)}" if missing else ""))
    else:
        check("every running job's restore point is on disk", True,
              f"skipped: {state_dir} is not mounted")

    return _finish(now, source, checks)


def _finish(now: datetime, source: str, checks: list[Check]) -> DrillResult:
    result = DrillResult(ran_at=now.isoformat(), source=source,
                         passed=all(c.ok for c in checks), checks=checks)
    try:
        result_path().write_text(result.to_json())
    except OSError:
        log.exception("Could not record the restore drill result")
    level = logging.INFO if result.passed else logging.ERROR
    log.log(level, "Restore drill %s (%s): %s", "passed" if result.passed else "FAILED",
            source, "; ".join(f"{c.name}: {'ok' if c.ok else 'FAIL'}" for c in checks))
    return result
