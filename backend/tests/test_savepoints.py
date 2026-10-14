"""Savepoint retention: what is kept, what is removed, and how."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import savepoints
from app import settings as settings_mod
from app.cluster import FlinkClusterClient
from app.models import Job, JobRun, RunState

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _job(db, name="sessions") -> Job:
    job = Job(name=name, sql_text="s", catalog_refs="[]")
    db.add(job)
    db.flush()
    return job


def _stopped(db, job, n, **kw) -> JobRun:
    """The nth stop of the job, each with its own savepoint."""
    run = JobRun(job_id=job.id, job_version=1, state=RunState.CANCELED.value,
                 started_at=T0 + timedelta(days=n), ended_at=T0 + timedelta(days=n, hours=1),
                 savepoint_path=f"file:///sp/savepoint-{n}", **kw)
    db.add(run)
    db.flush()
    return run


def _reload(db, job) -> Job:
    db.commit()
    db.expire(job)
    return job


def _paths(runs):
    return [r.savepoint_path for r in runs]


def test_keeps_the_newest_and_removes_the_rest_oldest_last(db):
    job = _job(db)
    for n in range(1, 6):
        _stopped(db, job, n)
    job = _reload(db, job)
    assert _paths(savepoints.to_remove(job, keep=3)) == ["file:///sp/savepoint-2", "file:///sp/savepoint-1"]


def test_keep_zero_removes_nothing(db):
    job = _job(db)
    for n in range(1, 6):
        _stopped(db, job, n)
    assert savepoints.to_remove(_reload(db, job), keep=0) == []


def test_never_removes_what_the_latest_run_started_from(db):
    job = _job(db)
    for n in range(1, 5):
        _stopped(db, job, n)
    # Started from an old savepoint and still running: it may need it until its
    # first checkpoint.
    db.add(JobRun(job_id=job.id, job_version=1, state=RunState.RUNNING.value,
                  started_at=T0 + timedelta(days=9), restored_from="file:///sp/savepoint-1"))
    job = _reload(db, job)
    assert _paths(savepoints.to_remove(job, keep=2)) == ["file:///sp/savepoint-2"]


def test_never_removes_the_restore_point(db):
    job = _job(db)
    for n in range(1, 4):
        _stopped(db, job, n)
    job = _reload(db, job)
    assert job.restore_point.path == "file:///sp/savepoint-3"
    # Even keeping none of the others, the one to resume from stays.
    assert "file:///sp/savepoint-3" not in _paths(savepoints.to_remove(job, keep=1))


def test_a_removed_savepoint_is_not_offered_to_resume_from(db):
    job = _job(db)
    _stopped(db, job, 1)
    _stopped(db, job, 2, savepoint_removed_at=T0)
    job = _reload(db, job)
    assert job.restore_point.path == "file:///sp/savepoint-1"
    assert job.latest_savepoint == "file:///sp/savepoint-1"


class _Cluster:
    def __init__(self, fail=()):
        self.disposed, self.fail = [], set(fail)

    async def dispose_savepoint(self, path):
        if path in self.fail:
            raise RuntimeError("storage unreachable")
        self.disposed.append(path)


class _Targets:
    def __init__(self, cluster):
        self._cluster = cluster

    def for_job(self, db, job):
        return job.target_name

    def cluster(self, target):
        return self._cluster


@pytest.fixture
def keep(monkeypatch):
    def _set(n):
        settings_mod.settings.cache_clear()
        monkeypatch.setenv("MARS_SAVEPOINTS_KEEP", str(n))
    yield _set
    settings_mod.settings.cache_clear()


@pytest.mark.asyncio
async def test_prune_removes_through_flink_and_records_it(db, keep):
    keep(2)
    job = _job(db)
    runs = [_stopped(db, job, n) for n in range(1, 5)]
    _reload(db, job)
    cluster = _Cluster(fail={"file:///sp/savepoint-1"})
    assert await savepoints.prune(db, _Targets(cluster)) == 1
    assert cluster.disposed == ["file:///sp/savepoint-2"]
    removed = {r.savepoint_path: r.savepoint_removed_at is not None for r in runs}
    # The one Flink could not remove is tried again next time.
    assert removed == {"file:///sp/savepoint-1": False, "file:///sp/savepoint-2": True,
                       "file:///sp/savepoint-3": False, "file:///sp/savepoint-4": False}


def test_off_when_keep_is_zero(keep):
    keep(0)
    assert not savepoints.is_due(datetime.now(timezone.utc))


def _flink(responses):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.content))
        return responses(request)

    client = FlinkClusterClient("http://flink:8081")
    client._client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        base_url="http://flink:8081", transport=httpx.MockTransport(handler))
    return client, calls


@pytest.mark.asyncio
async def test_dispose_asks_flink_and_waits_for_it():
    def responses(req):
        if req.method == "POST":
            return httpx.Response(202, json={"request-id": "r1"})
        return httpx.Response(200, json={"status": {"id": "COMPLETED"}, "operation": {}})

    client, calls = _flink(responses)
    await client.dispose_savepoint("file:///sp/savepoint-1")
    assert calls[0][:2] == ("POST", "/savepoint-disposal")
    assert b'"savepoint-path":"file:///sp/savepoint-1"' in calls[0][2].replace(b" ", b"")
    assert calls[1][:2] == ("GET", "/savepoint-disposal/r1")


@pytest.mark.asyncio
async def test_dispose_treats_an_already_missing_savepoint_as_done_and_reports_other_failures():
    def failing(trace):
        def responses(req):
            if req.method == "POST":
                return httpx.Response(202, json={"request-id": "r1"})
            return httpx.Response(200, json={"status": {"id": "COMPLETED"},
                                             "operation": {"failure-cause": {"stack-trace": trace}}})
        return responses

    client, _ = _flink(failing("java.io.FileNotFoundException: Cannot find meta data file"))
    await client.dispose_savepoint("file:///sp/gone")

    client, _ = _flink(failing("org.apache.flink.util.FlinkException: Could not dispose savepoint x.\n\tat a\nCaused by: java.io.IOException: Permission denied\n\tat b"))
    with pytest.raises(RuntimeError, match="^java.io.IOException: Permission denied$"):
        await client.dispose_savepoint("file:///sp/locked")
