"""Where a cluster's resources go: the machines, and each job's footprint."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app import resources
from app.cluster import CheckpointHealth, FlinkClusterClient
from app.models import Job, JobRun, RunState


@pytest.mark.asyncio
async def test_taskmanager_memory_and_cpu_come_from_flink_metrics(monkeypatch):
    calls = {"tm": 0}

    async def no_sleep(_):
        pass
    monkeypatch.setattr("app.cluster.asyncio.sleep", no_sleep)

    def handler(req):
        path = req.url.path
        if path == "/taskmanagers":
            return httpx.Response(200, json={"taskmanagers": [{"id": "tm:1", "slotsNumber": 12, "freeSlots": 3,
                                                              "hardware": {"cpuCores": 4}}]})
        if path == "/taskmanagers/tm:1/metrics":
            calls["tm"] += 1
            if calls["tm"] == 1:
                return httpx.Response(200, json=[])  # Flink's first, still-fetching answer
            return httpx.Response(200, json=[
                {"id": "Status.JVM.Memory.Heap.Used", "value": "173209600"},
                {"id": "Status.JVM.Memory.Heap.Max", "value": "939524096"},
                {"id": "Status.JVM.CPU.Load", "value": "0.25"},
                {"id": "Status.Flink.Memory.Managed.Used", "value": "0"},
                {"id": "Status.Flink.Memory.Managed.Total", "value": "858993470"}])
        if path == "/jobmanager/metrics":
            return httpx.Response(200, json=[{"id": "Status.JVM.Memory.Heap.Used", "value": "1.1E8"},
                                             {"id": "Status.JVM.Memory.Heap.Max", "value": "454164480"}])
        return httpx.Response(404)

    c = FlinkClusterClient("http://flink:8081")
    c._client = lambda: httpx.AsyncClient(base_url="http://flink:8081", transport=httpx.MockTransport(handler))
    r = await c.resources()
    tm = r["taskmanagers"][0]
    assert (tm["slots_total"], tm["slots_free"], tm["cpu_cores"], tm["cpu_load"]) == (12, 3, 4, 0.25)
    assert (tm["heap_used"], tm["heap_max"], tm["managed_total"]) == (173209600, 939524096, 858993470)
    assert r["jobmanager"] == {"heap_used": 110000000, "heap_max": 454164480}
    assert calls["tm"] == 2


def _vertex(name, parallelism, busy):
    return SimpleNamespace(name=name, parallelism=parallelism, busy_ratio=busy)


class _Cluster:
    def __init__(self, details):
        self.details = details

    async def resources(self):
        return {"taskmanagers": [], "jobmanager": {"heap_used": None, "heap_max": None}}

    async def job_detail(self, flink_job_id):
        return self.details.get(flink_job_id)


@pytest.mark.asyncio
async def test_jobs_on_the_cluster_are_listed_heaviest_first(db):
    for name, fid in (("small", "a" * 32), ("big", "b" * 32), ("elsewhere", "c" * 32)):
        job = Job(name=name, sql_text="s", catalog_refs="[]", target_name="mars-b" if name == "elsewhere" else None)
        db.add(job)
        db.flush()
        db.add(JobRun(job_id=job.id, job_version=1, state=RunState.RUNNING.value, flink_job_id=fid))
    db.commit()
    details = {
        "a" * 32: SimpleNamespace(vertices=[_vertex("Source", 1, 0.1)],
                                  checkpoints=CheckpointHealth(latest_completed_size_bytes=300, latest_completed_duration_ms=3)),
        "b" * 32: SimpleNamespace(vertices=[_vertex("Source", 2, 0.2), _vertex("Window", 4, 0.9)],
                                  checkpoints=CheckpointHealth(latest_completed_size_bytes=5_000_000, latest_completed_duration_ms=800)),
    }
    target = SimpleNamespace(name="default")
    registry = SimpleNamespace(
        cluster=lambda t: _Cluster(details),
        for_job=lambda db, job: SimpleNamespace(name=job.target_name or "default"),
    )
    out = await resources.cluster_resources(db, registry, target)
    assert [j["job"] for j in out["jobs"]] == ["big", "small"]  # not the one on mars-b
    big = out["jobs"][0]
    # Operators share slots, so a job holds as many as its widest operator.
    assert (big["slots"], big["busiest"], big["busy_ratio"], big["checkpoint_ms"]) == (4, "Window", 0.9, 800)
