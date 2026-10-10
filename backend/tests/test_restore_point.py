"""Which state a stopped or lost job resumes from.

The case this guards: a JobManager restart without HA makes Flink forget every
job. The supervisor then resubmits each one, and if it resumes from the newest
savepoint -- taken whenever someone last stopped the job by hand, possibly days
ago -- the job replays everything since into its sinks. A Kafka sink writes all of
it a second time. The checkpoint recorded while the job was alive is seconds old.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography.fernet import Fernet

from app.cluster import FlinkClusterClient, JobOverview
from app.models import Job, JobRun, RunState, Schedule, ScheduleMode
from app.secrets import SecretStore
from app.submitter import JobSubmitter

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
SAVEPOINT = "file:/flink-state/savepoints/savepoint-aaaa"
CHECKPOINT = "file:/flink-state/checkpoints/bbbb/chk-72237"


def _job(db) -> Job:
    job = Job(name="sit_sessionize", sql_text="s", catalog_refs="[]")
    db.add(job)
    db.flush()
    return job


def _run(db, job, **kw) -> JobRun:
    kw.setdefault("job_version", 1)
    kw.setdefault("state", RunState.FAILED.value)
    run = JobRun(job_id=job.id, **kw)
    db.add(run)
    db.flush()
    return run


def _refresh(db, job) -> Job:
    db.commit()
    db.expire(job)
    return job


# -- choosing the restore point ------------------------------------------------


def test_no_saved_state_means_no_restore_point(db):
    job = _job(db)
    _run(db, job, started_at=NOW)
    assert _refresh(db, job).restore_point is None


def test_a_crash_resumes_from_the_checkpoint_not_an_old_savepoint(db):
    job = _job(db)
    # Stopped by hand three days ago, then resumed and ran until the cluster lost it.
    _run(db, job, state=RunState.CANCELED.value, started_at=NOW - timedelta(days=4),
         ended_at=NOW - timedelta(days=3), savepoint_path=SAVEPOINT)
    _run(db, job, started_at=NOW - timedelta(days=3), ended_at=NOW,
         restored_from=SAVEPOINT, checkpoint_path=CHECKPOINT,
         checkpoint_at=NOW - timedelta(seconds=20))

    point = _refresh(db, job).restore_point
    assert point.kind == "checkpoint"
    assert point.path == CHECKPOINT


def test_a_deliberate_stop_resumes_from_its_savepoint(db):
    job = _job(db)
    # The savepoint taken at stop time is newer than any checkpoint before it.
    _run(db, job, state=RunState.CANCELED.value, started_at=NOW - timedelta(hours=1),
         ended_at=NOW, savepoint_path=SAVEPOINT, checkpoint_path=CHECKPOINT,
         checkpoint_at=NOW - timedelta(seconds=25))

    point = _refresh(db, job).restore_point
    assert point.kind == "savepoint"
    assert point.path == SAVEPOINT


def test_a_checkpoint_that_could_not_be_restored_is_not_retried(db):
    job = _job(db)
    _run(db, job, state=RunState.CANCELED.value, started_at=NOW - timedelta(days=4),
         ended_at=NOW - timedelta(days=3), savepoint_path=SAVEPOINT)
    _run(db, job, started_at=NOW - timedelta(days=3), ended_at=NOW - timedelta(minutes=2),
         checkpoint_path=CHECKPOINT, checkpoint_at=NOW - timedelta(minutes=2))
    # The resubmission from that checkpoint failed before checkpointing itself,
    # e.g. because Flink had already deleted it.
    _run(db, job, started_at=NOW - timedelta(minutes=1), ended_at=NOW,
         restored_from=CHECKPOINT)

    point = _refresh(db, job).restore_point
    assert point.kind == "savepoint", "a dead checkpoint must not keep the job down"
    assert point.path == SAVEPOINT


def test_a_later_checkpoint_supersedes_one_that_failed(db):
    job = _job(db)
    _run(db, job, started_at=NOW - timedelta(hours=2), checkpoint_path=CHECKPOINT,
         checkpoint_at=NOW - timedelta(hours=1))
    _run(db, job, started_at=NOW - timedelta(minutes=30), restored_from=CHECKPOINT,
         checkpoint_path=CHECKPOINT + "-next", checkpoint_at=NOW - timedelta(seconds=10))

    assert _refresh(db, job).restore_point.path == CHECKPOINT + "-next"


# -- recording checkpoints during reconcile ----------------------------------


class FakeCluster:
    def __init__(self, jobs, checkpoints):
        self.jobs = jobs
        self.checkpoints = checkpoints

    async def list_jobs(self):
        return [JobOverview(job_id=j, name="x", state=s) for j, s in self.jobs.items()]

    async def latest_checkpoints(self, job_ids):
        return {j: self.checkpoints[j] for j in job_ids if j in self.checkpoints}


def _submitter(cluster) -> JobSubmitter:
    return JobSubmitter(gateway=None, cluster=cluster,
                        store=SecretStore(key=Fernet.generate_key()))


@pytest.mark.asyncio
async def test_reconcile_records_the_checkpoint_and_keeps_it_after_the_job_is_lost(db):
    job = _job(db)
    run = _run(db, job, state=RunState.RUNNING.value, flink_job_id="a" * 32)
    db.commit()

    ack_ms = int(NOW.timestamp() * 1000)
    cluster = FakeCluster({"a" * 32: "RUNNING"}, {"a" * 32: (CHECKPOINT, ack_ms)})
    await _submitter(cluster).refresh_states(db)
    assert run.checkpoint_path == CHECKPOINT
    assert run.state == RunState.RUNNING.value

    # The JobManager restarts and forgets the job entirely.
    cluster.jobs, cluster.checkpoints = {}, {}
    await _submitter(cluster).refresh_states(db)
    assert run.state == RunState.FAILED.value
    assert run.checkpoint_path == CHECKPOINT, "the recorded path must survive the loss"
    assert _refresh(db, job).restore_point.path == CHECKPOINT


@pytest.mark.asyncio
async def test_reconcile_survives_a_failed_checkpoint_lookup(db):
    job = _job(db)
    run = _run(db, job, state=RunState.RUNNING.value, flink_job_id="a" * 32,
               checkpoint_path=CHECKPOINT, checkpoint_at=NOW)
    db.commit()

    class Broken(FakeCluster):
        async def latest_checkpoints(self, job_ids):
            raise httpx.ConnectError("refused")

    await _submitter(Broken({"a" * 32: "FAILED"}, {})).refresh_states(db)
    assert run.state == RunState.FAILED.value
    assert run.checkpoint_path == CHECKPOINT


# -- the supervisor -------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_resumes_a_lost_job_from_its_checkpoint(db, monkeypatch):
    from app import scheduler as mod

    job = _job(db)
    db.add(Schedule(job_id=job.id, mode=ScheduleMode.SUPERVISOR.value, enabled=True))
    _run(db, job, state=RunState.CANCELED.value, started_at=NOW - timedelta(days=4),
         ended_at=NOW - timedelta(days=3), savepoint_path=SAVEPOINT)
    _run(db, job, started_at=NOW - timedelta(days=3), ended_at=NOW,
         checkpoint_path=CHECKPOINT, checkpoint_at=NOW - timedelta(seconds=20))
    db.commit()

    @contextmanager
    def scope():
        yield db
        db.commit()

    monkeypatch.setattr(mod, "session_scope", scope)

    submitted = []

    class Recorder:
        async def submit(self, db, job, savepoint_path=None, **kw):
            submitted.append(savepoint_path)

    await mod.Scheduler(Recorder())._fire(job.id, ScheduleMode.SUPERVISOR.value)
    assert submitted == [CHECKPOINT]


# -- reading checkpoint locations from Flink ------------------------------------


@pytest.mark.asyncio
async def test_latest_checkpoints_reads_only_restorable_paths():
    payloads = {
        "a" * 32: {"latest": {"completed": {
            "external_path": CHECKPOINT, "latest_ack_timestamp": 1791665557000}}},
        # Held only in JobManager memory: useless once that JobManager is gone.
        "b" * 32: {"latest": {"completed": {
            "external_path": "<checkpoint-not-externally-addressable>",
            "latest_ack_timestamp": 1791665557000}}},
        "c" * 32: {"latest": {"completed": None}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        job_id = request.url.path.split("/")[2]
        if job_id in payloads:
            return httpx.Response(200, json=payloads[job_id])
        return httpx.Response(404)

    client = FlinkClusterClient("http://flink:8081")
    client._client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        base_url="http://flink:8081", transport=httpx.MockTransport(handler))

    out = await client.latest_checkpoints(["a" * 32, "b" * 32, "c" * 32, "d" * 32])
    assert out == {"a" * 32: (CHECKPOINT, 1791665557000)}
