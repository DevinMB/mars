"""Client for the Flink REST API -- the read side of the console.

The SQL Gateway starts jobs; this is how MARS sees what they are doing afterwards:
state, uptime, checkpoint health, and why something failed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)

# Flink job states that mean the job is no longer doing work.
TERMINAL_STATES = {"FINISHED", "FAILED", "CANCELED"}


@dataclass
class JobOverview:
    job_id: str
    name: str
    state: str
    start_time: int | None = None
    end_time: int | None = None
    duration_ms: int | None = None

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES


@dataclass
class CheckpointHealth:
    completed: int = 0
    failed: int = 0
    # Milliseconds since the last successful checkpoint completed. A value that
    # keeps climbing is the earliest visible sign of a stuck job.
    latest_completed_age_ms: int | None = None
    latest_completed_size_bytes: int | None = None
    in_progress: int = 0


@dataclass
class ClusterInfo:
    flink_version: str = ""
    taskmanagers: int = 0
    slots_total: int = 0
    slots_available: int = 0
    jobs_running: int = 0
    jobs_failed: int = 0


@dataclass
class VertexBackpressure:
    name: str
    busy_ratio: float | None = None
    backpressured_ratio: float | None = None


@dataclass
class JobDetail:
    overview: JobOverview
    checkpoints: CheckpointHealth = field(default_factory=CheckpointHealth)
    vertices: list[VertexBackpressure] = field(default_factory=list)
    exception: str | None = None


class FlinkClusterClient:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base, timeout=self._timeout)

    async def reachable(self) -> bool:
        try:
            await self.info()
            return True
        except (httpx.HTTPError, KeyError, ValueError):
            return False

    async def info(self) -> ClusterInfo:
        async with self._client() as c:
            r = await c.get("/overview")
            r.raise_for_status()
            d = r.json()
        return ClusterInfo(
            flink_version=d.get("flink-version", ""),
            taskmanagers=d.get("taskmanagers", 0),
            slots_total=d.get("slots-total", 0),
            slots_available=d.get("slots-available", 0),
            jobs_running=d.get("jobs-running", 0),
            jobs_failed=d.get("jobs-failed", 0),
        )

    async def list_jobs(self) -> list[JobOverview]:
        async with self._client() as c:
            r = await c.get("/jobs/overview")
            r.raise_for_status()
            d = r.json()
        return [_overview(j) for j in d.get("jobs", [])]

    async def get_job(self, job_id: str) -> JobOverview | None:
        async with self._client() as c:
            r = await c.get(f"/jobs/{job_id}")
            if r.status_code == 404:
                return None
            r.raise_for_status()
            d = r.json()
        return JobOverview(
            job_id=d.get("jid", job_id),
            name=d.get("name", ""),
            state=d.get("state", "UNKNOWN"),
            start_time=d.get("start-time"),
            end_time=d.get("end-time") if d.get("end-time", -1) > 0 else None,
            duration_ms=d.get("duration"),
        )

    async def job_detail(self, job_id: str) -> JobDetail | None:
        overview = await self.get_job(job_id)
        if overview is None:
            return None

        detail = JobDetail(overview=overview)
        async with self._client() as c:
            detail.checkpoints = await self._checkpoints(c, job_id)
            detail.exception = await self._root_exception(c, job_id)
            detail.vertices = await self._backpressure(c, job_id)
        return detail

    async def cancel(self, job_id: str) -> None:
        async with self._client() as c:
            r = await c.patch(f"/jobs/{job_id}?mode=cancel")
            if r.status_code not in (200, 202, 404):
                r.raise_for_status()

    async def trigger_savepoint(self, job_id: str, target_dir: str | None = None) -> str:
        """Starts a savepoint and returns the request id to poll."""
        body: dict[str, Any] = {"cancel-job": False}
        if target_dir:
            body["target-directory"] = target_dir
        async with self._client() as c:
            r = await c.post(f"/jobs/{job_id}/savepoints", json=body)
            r.raise_for_status()
            return r.json()["request-id"]

    async def savepoint_status(self, job_id: str, request_id: str) -> dict[str, Any]:
        async with self._client() as c:
            r = await c.get(f"/jobs/{job_id}/savepoints/{request_id}")
            r.raise_for_status()
            return r.json()

    # -- internals ----------------------------------------------------------

    async def _checkpoints(self, c: httpx.AsyncClient, job_id: str) -> CheckpointHealth:
        health = CheckpointHealth()
        try:
            r = await c.get(f"/jobs/{job_id}/checkpoints")
            if r.status_code != 200:
                return health
            d = r.json()
        except httpx.HTTPError:
            return health

        counts = d.get("counts", {})
        health.completed = counts.get("completed", 0)
        health.failed = counts.get("failed", 0)
        health.in_progress = counts.get("in_progress", 0)

        latest = (d.get("latest") or {}).get("completed")
        if latest:
            health.latest_completed_size_bytes = latest.get("state_size")
            ts = latest.get("latest_ack_timestamp") or latest.get("trigger_timestamp")
            if ts:
                import time as _t

                health.latest_completed_age_ms = max(0, int(_t.time() * 1000) - int(ts))
        return health

    async def _root_exception(self, c: httpx.AsyncClient, job_id: str) -> str | None:
        try:
            r = await c.get(f"/jobs/{job_id}/exceptions?maxExceptions=1")
            if r.status_code != 200:
                return None
            d = r.json()
        except httpx.HTTPError:
            return None

        root = d.get("rootException")
        if root:
            return root
        history = d.get("exceptionHistory", {}).get("entries", [])
        if history:
            return history[0].get("stacktrace")
        return None

    async def _backpressure(
        self, c: httpx.AsyncClient, job_id: str
    ) -> list[VertexBackpressure]:
        out: list[VertexBackpressure] = []
        try:
            r = await c.get(f"/jobs/{job_id}")
            if r.status_code != 200:
                return out
            vertices = r.json().get("vertices", [])
        except httpx.HTTPError:
            return out

        for v in vertices:
            metrics = v.get("metrics", {})
            out.append(
                VertexBackpressure(
                    name=v.get("name", "")[:120],
                    busy_ratio=metrics.get("accumulated-busy-time"),
                    backpressured_ratio=metrics.get("accumulated-backpressured-time"),
                )
            )
        return out


def _overview(j: dict[str, Any]) -> JobOverview:
    return JobOverview(
        job_id=j.get("jid", ""),
        name=j.get("name", ""),
        state=j.get("state", "UNKNOWN"),
        start_time=j.get("start-time"),
        end_time=j.get("end-time") if j.get("end-time", -1) > 0 else None,
        duration_ms=j.get("duration"),
    )
