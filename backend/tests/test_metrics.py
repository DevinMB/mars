"""The metrics alerts depend on.

Each guards a failure Flink's own metrics cannot show: a failed job vanishes from
them, a job MARS keeps restarting looks healthy between restarts, and MARS losing
track of checkpoints changes nothing in Flink at all.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from prometheus_client import REGISTRY

from app import metrics
from app.models import Job, JobRun, RunState, Schedule, ScheduleMode

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def value(name: str, **labels) -> float | None:
    return REGISTRY.get_sample_value(name, labels or None)


def _job(db, name: str, **run) -> Job:
    job = Job(name=name, sql_text="s", catalog_refs="[]")
    db.add(job)
    db.flush()
    if run:
        db.add(JobRun(job_id=job.id, job_version=1, **run))
    db.commit()
    db.expire(job)
    return job


def test_only_unacknowledged_failures_count_as_needing_attention(db):
    _job(db, "broken", state=RunState.FAILED.value, started_at=NOW)
    _job(db, "known", state=RunState.FAILED.value, started_at=NOW,
         acknowledged_at=NOW, acknowledged_by="operator")
    _job(db, "fine", state=RunState.RUNNING.value, started_at=NOW)

    metrics.refresh(db, now=NOW)
    assert value("mars_jobs_failed") == 2
    assert value("mars_jobs_failed_unacknowledged") == 1
    assert value("mars_jobs_running") == 1


def test_restore_point_age_tracks_the_recorded_checkpoint(db):
    _job(db, "recording", state=RunState.RUNNING.value, started_at=NOW - timedelta(hours=2),
         checkpoint_path="file:/cp/chk-9", checkpoint_at=NOW - timedelta(seconds=20))

    metrics.refresh(db, now=NOW)
    assert value("mars_restore_point_age_seconds", mars_job="recording") == 20


def test_an_old_savepoint_does_not_hide_a_run_that_never_recorded(db):
    job = _job(db, "stuck")
    db.add(JobRun(job_id=job.id, job_version=1, state=RunState.CANCELED.value,
                  started_at=NOW - timedelta(days=3), ended_at=NOW - timedelta(days=2),
                  savepoint_path="file:/sp/savepoint-1"))
    db.add(JobRun(job_id=job.id, job_version=1, state=RunState.RUNNING.value,
                  started_at=NOW - timedelta(hours=1)))
    db.commit()
    db.expire(job)

    metrics.refresh(db, now=NOW)
    # Measured from when this run started, not from the two-day-old savepoint, and
    # not hidden either: an hour without a recorded checkpoint is the signal.
    assert value("mars_restore_point_age_seconds", mars_job="stuck") == 3600


def test_a_job_that_stops_running_stops_being_reported(db):
    job = _job(db, "stopping", state=RunState.RUNNING.value, started_at=NOW)
    metrics.refresh(db, now=NOW)
    assert value("mars_restore_point_age_seconds", mars_job="stopping") == 0

    job.runs[0].state = RunState.CANCELED.value
    db.commit()
    metrics.refresh(db, now=NOW)
    assert value("mars_restore_point_age_seconds", mars_job="stopping") is None


@pytest.mark.asyncio
async def test_supervisor_resubmissions_are_counted_per_job(db, monkeypatch):
    from app import scheduler as mod

    job = _job(db, "flaky", state=RunState.FAILED.value, started_at=NOW)
    db.add(Schedule(job_id=job.id, mode=ScheduleMode.SUPERVISOR.value, enabled=True))
    db.commit()

    @contextmanager
    def scope():
        yield db
        db.commit()

    monkeypatch.setattr(mod, "session_scope", scope)

    class Recorder:
        async def submit(self, db, job, **kw):
            pass

        async def cluster_reachable(self):
            return True

    before = value("mars_supervisor_resubmissions_total", mars_job="flaky") or 0
    await mod.Scheduler(Recorder())._fire(job.id, ScheduleMode.SUPERVISOR.value)
    await mod.Scheduler(Recorder())._fire(job.id, ScheduleMode.SUPERVISOR.value)
    assert value("mars_supervisor_resubmissions_total", mars_job="flaky") == before + 2


@pytest.mark.asyncio
async def test_submissions_are_counted_by_outcome(db, monkeypatch):
    from app.submitter import JobSubmitter, SubmissionError

    sub = JobSubmitter(gateway=None, cluster=None, store=None)
    started = value("mars_job_submissions_total", outcome="started") or 0
    failed = value("mars_job_submissions_total", outcome="failed") or 0

    async def ok(*a, **k):
        return "run"

    async def boom(*a, **k):
        raise SubmissionError("gateway down")

    monkeypatch.setattr(sub, "_submit", ok)
    assert await sub.submit(db, job=None) == "run"
    monkeypatch.setattr(sub, "_submit", boom)
    with pytest.raises(SubmissionError):
        await sub.submit(db, job=None)

    assert value("mars_job_submissions_total", outcome="started") == started + 1
    assert value("mars_job_submissions_total", outcome="failed") == failed + 1
