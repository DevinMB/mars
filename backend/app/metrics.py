"""What MARS publishes at /metrics: the things only MARS knows about its jobs.

Flink's own metrics cover a job while it runs. They cannot cover a job that has
stopped: a failed job disappears from Flink's metrics, so an alert on checkpoint
progress goes quiet exactly when the job is gone. MARS still has the record, so
these fill that gap.
"""
from __future__ import annotations

from datetime import datetime, timezone

from prometheus_client import Counter, Gauge
from sqlalchemy.orm import Session

from .models import Job, RunState, _aware

JOBS_RUNNING = Gauge("mars_jobs_running", "Jobs MARS believes are running")
JOBS_FAILED = Gauge("mars_jobs_failed", "Jobs whose most recent run failed")
JOBS_FAILED_UNACKNOWLEDGED = Gauge(
    "mars_jobs_failed_unacknowledged",
    "Jobs whose most recent run failed and nobody has marked the failure as dealt with",
)
RESTORE_POINT_AGE = Gauge(
    "mars_restore_point_age_seconds",
    "For each running job, how old the newest state MARS could resume it from is. "
    "Grows past the checkpoint interval only if MARS has stopped recording checkpoints.",
    ["mars_job"],
)
# Labelled mars_job, not job: Prometheus reserves `job` for the scrape job and
# would rename ours to exported_job.
SUPERVISOR_RESUBMISSIONS = Counter(
    "mars_supervisor_resubmissions_total",
    "Times the supervisor restarted a stopped job. Rising steadily means a job keeps dying.",
    ["mars_job"],
)
SUBMISSIONS = Counter("mars_job_submissions_total", "Job submissions", ["outcome"])


def refresh(db: Session, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    running = failed = unacknowledged = 0
    ages: dict[str, float] = {}
    for job in db.query(Job).all():
        latest = job.runs[0] if job.runs else None
        if latest is None:
            continue
        if latest.state == RunState.RUNNING.value:
            running += 1
            # The newest restore point, but never older than the run itself: a
            # savepoint from before this run started says nothing about whether
            # this run's checkpoints are being recorded.
            started = _aware(latest.started_at)
            point = job.restore_point
            newest = max(point.taken_at, started) if point else started
            ages[job.name] = max(0.0, (now - newest).total_seconds())
        elif latest.state == RunState.FAILED.value:
            failed += 1
            if latest.acknowledged_at is None:
                unacknowledged += 1

    JOBS_RUNNING.set(running)
    JOBS_FAILED.set(failed)
    JOBS_FAILED_UNACKNOWLEDGED.set(unacknowledged)
    # Cleared each time, so a job that stops running stops being reported rather
    # than holding its last age forever.
    RESTORE_POINT_AGE.clear()
    for name, age in ages.items():
        RESTORE_POINT_AGE.labels(mars_job=name).set(age)
