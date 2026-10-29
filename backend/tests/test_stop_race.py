"""A deliberate stop must not be undone by the supervisor.

Stop-with-savepoint makes Flink report the job FINISHED a moment before the
savepoint is confirmed. Reconcile used to record that as an ordinary finish, and
the supervisor -- which restarts finished and failed streaming jobs -- resubmitted
the job from its last checkpoint, which Flink deletes when a job finishes. Seen
three times in maintenance windows on 27-28 Oct 2026: each one a failed restore,
minutes of extra downtime, and a page for a restart loop that was only a reboot.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import httpx
import pytest
from cryptography.fernet import Fernet

from app.cluster import JobOverview
from app.metrics import SUPERVISOR_RESUBMISSIONS
from app.models import Job, JobRun, RunState, Schedule, ScheduleMode
from app.secrets import SecretStore
from app.submitter import JobSubmitter, SubmissionError

NOW = datetime(2026, 10, 28, 22, 4, tzinfo=timezone.utc)
FLINK_ID = "f" * 32
SAVEPOINT = "file:/flink-savepoints/savepoint-f5ec23-66baf6284e65"
CHECKPOINT = "file:/flink-state/checkpoints/ffff/chk-45140"


class Cluster:
    """Flink as the window sees it: the job ends before its savepoint is confirmed."""

    def __init__(self, state="RUNNING", up=True):
        self.state = state
        self.up = up
        self.during_wait = None

    async def reachable(self):
        return self.up

    async def list_jobs(self):
        if not self.up:
            raise httpx.ConnectError("refused")
        return [JobOverview(job_id=FLINK_ID, name="mars:buoys_hourly", state=self.state)] if self.state else []

    async def latest_checkpoints(self, job_ids):
        return {j: (CHECKPOINT, int(NOW.timestamp() * 1000)) for j in job_ids}

    async def state_size(self, job_id):
        return 1_000_000

    async def stop_with_savepoint(self, job_id, target_dir, drain=False, native=False):
        return "request-1"

    async def await_savepoint(self, job_id, request_id, budget):
        self.state = "FINISHED"
        if self.during_wait:
            await self.during_wait()
        return SAVEPOINT


def _submitter(cluster) -> JobSubmitter:
    return JobSubmitter(gateway=None, cluster=cluster, store=SecretStore(key=Fernet.generate_key()))


def _supervised_job(db) -> tuple[Job, JobRun]:
    job = Job(name="buoys_hourly", sql_text="s", catalog_refs="[]")
    db.add(job)
    db.flush()
    db.add(Schedule(job_id=job.id, mode=ScheduleMode.SUPERVISOR.value, enabled=True))
    run = JobRun(job_id=job.id, job_version=1, state=RunState.RUNNING.value, flink_job_id=FLINK_ID,
                 started_at=NOW, checkpoint_path=CHECKPOINT, checkpoint_at=NOW)
    db.add(run)
    db.commit()
    return job, run


def _scheduler(monkeypatch, db, submitter):
    from app import scheduler as mod

    @contextmanager
    def scope():
        yield db
        db.commit()

    monkeypatch.setattr(mod, "session_scope", scope)
    return mod.Scheduler(submitter)


@pytest.mark.asyncio
async def test_a_reconcile_during_the_stop_does_not_hand_the_job_to_the_supervisor(db, monkeypatch):
    job, run = _supervised_job(db)
    cluster = Cluster()
    sub = _submitter(cluster)
    scheduler = _scheduler(monkeypatch, db, sub)
    verdicts = []

    async def reconcile_mid_stop():
        # The scheduler's tick lands between Flink finishing the job and the
        # savepoint being confirmed: the exact window of the original race.
        await sub.refresh_states(db)
        db.expire(job)
        verdicts.append((run.state, scheduler._should_fire(db, job.schedule, job)))

    cluster.during_wait = reconcile_mid_stop
    path = await sub.stop_with_savepoint(db, run)

    assert verdicts == [(RunState.CANCELED.value, False)], "mid-stop, the run must not read as finished"
    assert path == SAVEPOINT
    assert run.state == RunState.CANCELED.value and run.savepoint_path == SAVEPOINT
    db.expire(job)
    assert job.restore_point.path == SAVEPOINT


@pytest.mark.asyncio
async def test_a_cluster_restart_during_the_stop_is_not_a_lost_job(db):
    # The patch run reboots the host straight after the window's stop: Flink can
    # forget the job before the stop has recorded anything.
    _, run = _supervised_job(db)
    from app.models import utcnow
    run.stop_requested_at = utcnow()
    db.commit()

    await _submitter(Cluster(state=None)).refresh_states(db)
    assert run.state == RunState.CANCELED.value
    assert run.error_summary is None


@pytest.mark.asyncio
async def test_an_ordinary_finish_still_reads_as_finished(db):
    _, run = _supervised_job(db)
    await _submitter(Cluster(state="FINISHED")).refresh_states(db)
    assert run.state == RunState.FINISHED.value


@pytest.mark.asyncio
async def test_a_failed_stop_clears_its_mark(db):
    _, run = _supervised_job(db)

    class Refuses(Cluster):
        async def stop_with_savepoint(self, *a, **kw):
            raise httpx.ConnectError("refused")

    with pytest.raises(SubmissionError):
        await _submitter(Refuses()).stop_with_savepoint(db, run)
    assert run.state == RunState.RUNNING.value
    assert run.stop_requested_at is None, "a job left running must be supervised as before"


@pytest.mark.asyncio
async def test_the_supervisor_waits_for_an_unreachable_cluster(db, monkeypatch):
    job, run = _supervised_job(db)
    run.state = RunState.FAILED.value
    db.commit()

    submitted = []

    class Down:
        async def cluster_reachable(self):
            return False

        async def submit(self, *a, **kw):
            submitted.append(kw)

    scheduler = _scheduler(monkeypatch, db, Down())
    before = SUPERVISOR_RESUBMISSIONS.labels(mars_job=job.name)._value.get()
    await scheduler._fire(job.id, ScheduleMode.SUPERVISOR.value)
    assert submitted == []
    assert SUPERVISOR_RESUBMISSIONS.labels(mars_job=job.name)._value.get() == before
    assert db.query(JobRun).filter_by(job_id=job.id).count() == 1, "no failed run per tick"
