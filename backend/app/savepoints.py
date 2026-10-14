"""Removes old savepoints, keeping the newest few per job.

Flink never deletes a savepoint: it is the user's, by design. MARS takes one
every time a job is stopped, by a person, the maintenance window or the restore
drill, so without this they pile up for good. Small for a light job; for one
with real state (a large join, long windows) each can be gigabytes.

What is kept, whatever the count:

* the newest ``savepoints_keep`` per job;
* the state the job would resume from now (``Job.restore_point``);
* whatever the job's latest run started from, which that run can still need
  until its first checkpoint completes.

Removal goes through Flink (``POST /savepoint-disposal``) on the job's cluster,
so it works for local disk, a shared mount or object storage alike, without the
console touching any files. The run keeps the path and records when it was
removed. Savepoints MARS never recorded, such as one taken by hand in Flink, are
left alone.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .metrics import SAVEPOINTS_REMOVED, SAVEPOINT_REMOVAL_FAILURES
from .models import Job, JobRun, utcnow
from .settings import settings

log = logging.getLogger(__name__)

EVERY = timedelta(hours=1)
# Per pass, so a first run over a long history does not hit Flink all at once.
BATCH = 25

_last_run: datetime | None = None


def is_due(now: datetime) -> bool:
    if settings().savepoints_keep <= 0:
        return False
    return _last_run is None or _last_run + EVERY <= now


def to_remove(job: Job, keep: int) -> list[JobRun]:
    """This job's savepoints that retention would remove, oldest last."""
    if keep <= 0:
        return []
    protected = set()
    point = job.restore_point
    if point is not None:
        protected.add(point.path)
    if job.runs and job.runs[0].restored_from:
        protected.add(job.runs[0].restored_from)

    # Runs come newest first.
    present = [r for r in job.runs if r.savepoint_path and not r.savepoint_removed_at]
    return [r for r in present[keep:] if r.savepoint_path not in protected]


async def prune(db: Session, targets) -> int:
    """One pass over every job; returns how many savepoints were removed."""
    global _last_run
    _last_run = datetime.now(timezone.utc)
    keep = settings().savepoints_keep
    removed = 0
    budget = BATCH
    for job in db.query(Job).order_by(Job.name):
        candidates = to_remove(job, keep)[:budget]
        if not candidates:
            continue
        try:
            cluster = targets.cluster(targets.for_job(db, job))
        except Exception as exc:
            log.warning("Savepoint retention: no cluster for job '%s': %s", job.name, exc)
            continue
        for run in candidates:
            budget -= 1
            try:
                await cluster.dispose_savepoint(run.savepoint_path)
            except Exception as exc:
                SAVEPOINT_REMOVAL_FAILURES.inc()
                log.warning("Could not remove savepoint %s of job '%s': %s",
                            run.savepoint_path, job.name, exc)
                continue
            run.savepoint_removed_at = utcnow()
            db.commit()
            removed += 1
            SAVEPOINTS_REMOVED.inc()
            log.info("Removed savepoint %s of job '%s' (keeping the newest %d)",
                     run.savepoint_path, job.name, keep)
        if budget <= 0:
            break
    return removed
