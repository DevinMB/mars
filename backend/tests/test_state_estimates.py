"""Waits and estimates that scale with a job's state, from measured speed."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app import state_estimates as est
from app.cluster import FlinkClusterClient, SavepointStillRunning
from app.models import Job, JobRun, RunState
from app.submitter import JobSubmitter, SubmissionError

GB = 1024 ** 3


def _job(db):
    job = Job(name="big", sql_text="s", catalog_refs="[]")
    db.add(job)
    db.flush()
    return job


def test_the_rate_is_measured_once_there_are_large_savepoints(db):
    assert est.rate(db) == est.Rate(est.ASSUMED_RATE, measured=False)
    job = _job(db)
    # A tiny one says nothing about speed; three large ones at 100, 200, 300 MB/s.
    db.add(JobRun(job_id=job.id, job_version=1, state="canceled", savepoint_bytes=20_000, savepoint_ms=900))
    for mb_s in (100, 200, 300):
        db.add(JobRun(job_id=job.id, job_version=1, state="canceled",
                      savepoint_bytes=10 * GB, savepoint_ms=int(10 * 1024 / mb_s * 1000)))
    db.commit()
    r = est.rate(db)
    assert r.measured and abs(r.bytes_per_second / 1024 ** 2 - 200) < 1


def test_a_hundred_gigabytes_gets_hours_not_three_minutes():
    r = est.Rate(est.ASSUMED_RATE, measured=False)
    assert est.savepoint_budget(None, r) == est.savepoint_budget(20_000, r) == 180
    budget = est.savepoint_budget(100 * GB, r)
    assert 3600 < budget <= est.CEILING_SECONDS
    # Written then read at 50 MB/s: a little over an hour stopped.
    assert 60 * 60 < est.expected_pause(100 * GB, r) < 75 * 60
    assert est.expected_pause(20_000, r) < 10


def _client(handler):
    c = FlinkClusterClient("http://flink:8081")
    c._client = lambda: httpx.AsyncClient(base_url="http://flink:8081", transport=httpx.MockTransport(handler))
    return c


@pytest.mark.asyncio
async def test_native_format_is_asked_for_only_when_chosen():
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        return httpx.Response(202, json={"request-id": "r"})

    c = _client(handler)
    await c.stop_with_savepoint("a" * 32)
    await c.stop_with_savepoint("a" * 32, native=True)
    assert "formatType" not in bodies[0] and bodies[1]["formatType"] == "NATIVE"


@pytest.mark.asyncio
async def test_a_savepoint_still_being_written_is_not_called_a_failure():
    c = _client(lambda req: httpx.Response(200, json={"status": {"id": "IN_PROGRESS"}}))
    with pytest.raises(SavepointStillRunning):
        await c.await_savepoint("a" * 32, "r", budget=0.3)


class _Cluster:
    def __init__(self, size, still_running=False):
        self.size, self.still_running, self.native = size, still_running, None

    async def state_size(self, job_id):
        return self.size

    async def stop_with_savepoint(self, job_id, target_dir=None, drain=False, native=False):
        self.native = native
        return "req"

    async def await_savepoint(self, job_id, request_id, budget=180.0):
        self.budget = budget
        if self.still_running:
            raise SavepointStillRunning("still writing")
        return "file:/flink-savepoints/savepoint-x"


def _submitter(cluster):
    return JobSubmitter(None, cluster, SimpleNamespace(redact=lambda db, s: s))


@pytest.mark.asyncio
async def test_stopping_scales_the_wait_and_records_size_and_time(db):
    job = _job(db)
    run = JobRun(job_id=job.id, job_version=1, state=RunState.RUNNING.value, flink_job_id="a" * 32)
    db.add(run)
    db.commit()
    cluster = _Cluster(100 * GB)
    await _submitter(cluster).stop_with_savepoint(db, run, native=True)
    assert cluster.budget > 3600 and cluster.native is True
    assert run.savepoint_bytes == 100 * GB and run.savepoint_ms is not None
    assert run.state == RunState.CANCELED.value


@pytest.mark.asyncio
async def test_giving_up_says_the_job_will_still_stop(db):
    job = _job(db)
    run = JobRun(job_id=job.id, job_version=1, state=RunState.RUNNING.value, flink_job_id="a" * 32)
    db.add(run)
    db.commit()
    with pytest.raises(SubmissionError, match="still writing") as exc:
        await _submitter(_Cluster(GB, still_running=True)).stop_with_savepoint(db, run)
    assert "left running" not in exc.value.summary
    assert run.state == RunState.RUNNING.value
