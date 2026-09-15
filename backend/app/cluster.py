"""Client for the Flink REST API -- the read side of the console.

The SQL Gateway starts jobs; this is how MARS sees what they are doing afterwards:
state, uptime, checkpoint health, and why something failed.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
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
    latest_completed_duration_ms: int | None = None
    in_progress: int = 0
    restored: int = 0
    # The configured interval, so age can be judged against what this job asked
    # for rather than against a number hardcoded in the console. An age of four
    # intervals means something is wrong; four intervals is 2 minutes on one job
    # and 2 hours on another.
    interval_ms: int | None = None
    timeout_ms: int | None = None

    @property
    def stalled(self) -> bool:
        """True when checkpoints should have completed by now and have not."""
        if self.latest_completed_age_ms is None or not self.interval_ms:
            return False
        return self.latest_completed_age_ms > 3 * self.interval_ms


@dataclass
class ClusterInfo:
    flink_version: str = ""
    taskmanagers: int = 0
    slots_total: int = 0
    slots_available: int = 0
    jobs_running: int = 0
    jobs_failed: int = 0


@dataclass
class VertexHealth:
    """One operator in the job graph, with the numbers that explain its state.

    Ratios are 0..1 taken from Flink's own backpressure sampling, not from the
    accumulated-*-time counters on the job graph: those are cumulative
    milliseconds since the task started, so a job that was briefly busy hours ago
    looks permanently busy if you read them as a rate.
    """

    id: str
    name: str
    status: str = ""
    parallelism: int = 0
    backpressure_level: str | None = None  # ok | low | high
    busy_ratio: float | None = None
    backpressured_ratio: float | None = None
    records_in: int | None = None
    records_out: int | None = None
    records_in_rate: float | None = None
    records_out_rate: float | None = None
    # Highest consumer lag across this operator's subtasks. Only sources report
    # it, and Kafka reports NaN when the consumer has not fetched recently, so a
    # None here means "not applicable", never "zero".
    kafka_lag_max: float | None = None


@dataclass
class JobDetail:
    overview: JobOverview
    checkpoints: CheckpointHealth = field(default_factory=CheckpointHealth)
    vertices: list[VertexHealth] = field(default_factory=list)
    exception: str | None = None
    restarts: int | None = None


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
            # Independent reads; a slow one should not serialise the others.
            checkpoints, exception, vertices, restarts = await asyncio.gather(
                self._checkpoints(c, job_id),
                self._root_exception(c, job_id),
                self._vertices(c, job_id),
                self._restarts(c, job_id),
                return_exceptions=True,
            )
        detail.checkpoints = _or(checkpoints, CheckpointHealth())
        detail.exception = _or(exception, None)
        detail.vertices = _or(vertices, [])
        detail.restarts = _or(restarts, None)
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

    async def stop_with_savepoint(
        self, job_id: str, target_dir: str | None = None, drain: bool = False
    ) -> str:
        """Stops a job after writing its state, and returns the request id.

        Not the same as cancelling. Cancel throws the state away; this writes it
        somewhere durable first so the job can be started again where it left
        off. ``drain`` advances the watermark to the end of time first, which
        flushes pending windows -- correct when retiring a job for good, wrong
        when it is coming back, since event time cannot go backwards afterwards.
        """
        body: dict[str, Any] = {"drain": drain}
        if target_dir:
            body["targetDirectory"] = target_dir
        async with self._client() as c:
            r = await c.post(f"/jobs/{job_id}/stop", json=body)
            r.raise_for_status()
            return r.json()["request-id"]

    async def await_savepoint(
        self, job_id: str, request_id: str, budget: float = 180.0
    ) -> str:
        """Waits for a savepoint to finish and returns where it was written.

        Raises RuntimeError with Flink's own reason if it fails. A savepoint that
        fails must not be reported as success: the caller would record a path
        that does not exist and a later resume would fail at submission, long
        after anyone connected the two.
        """
        deadline = time.monotonic() + budget
        delay = 0.25
        while time.monotonic() < deadline:
            body = await self.savepoint_status(job_id, request_id)
            status = (body.get("status") or {}).get("id")
            if status == "COMPLETED":
                operation = body.get("operation") or {}
                failure = operation.get("failure-cause")
                if failure:
                    raise RuntimeError(
                        failure.get("stack-trace")
                        or str(failure.get("serialized-throwable", "Savepoint failed"))
                    )
                location = operation.get("location")
                if not location:
                    raise RuntimeError("Flink reported no savepoint location.")
                return location
            await asyncio.sleep(delay)
            delay = min(delay * 1.4, 2.0)
        raise RuntimeError(f"The savepoint did not finish within {budget:.0f}s.")

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
        health.restored = counts.get("restored", 0)

        latest = (d.get("latest") or {}).get("completed")
        if latest:
            health.latest_completed_size_bytes = latest.get("state_size")
            health.latest_completed_duration_ms = latest.get("end_to_end_duration")
            ts = latest.get("latest_ack_timestamp") or latest.get("trigger_timestamp")
            if ts:
                health.latest_completed_age_ms = max(
                    0, int(time.time() * 1000) - int(ts)
                )

        # The configured interval gives the age a yardstick.
        try:
            rc = await c.get(f"/jobs/{job_id}/checkpoints/config")
            if rc.status_code == 200:
                cfg = rc.json()
                health.interval_ms = _int(cfg.get("interval"))
                health.timeout_ms = _int(cfg.get("timeout"))
        except httpx.HTTPError:
            pass
        return health

    async def _restarts(self, c: httpx.AsyncClient, job_id: str) -> int | None:
        try:
            r = await c.get(f"/jobs/{job_id}/metrics", params={"get": "numRestarts"})
            if r.status_code != 200:
                return None
            for m in r.json():
                return _int(m.get("value"))
        except httpx.HTTPError:
            return None
        return None

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

    async def _vertices(
        self, c: httpx.AsyncClient, job_id: str
    ) -> list[VertexHealth]:
        try:
            r = await c.get(f"/jobs/{job_id}")
            if r.status_code != 200:
                return []
            vertices = r.json().get("vertices", [])
        except httpx.HTTPError:
            return []

        out: list[VertexHealth] = []
        for v in vertices:
            m = v.get("metrics", {})
            out.append(
                VertexHealth(
                    id=v.get("id", ""),
                    name=v.get("name", "")[:200],
                    status=v.get("status", ""),
                    parallelism=v.get("parallelism", 0) or 0,
                    # Deliberately not read-records/write-records from here:
                    # those count only what crosses a network boundary, and
                    # Flink chains Source -> Calc -> Sink into a single task, so
                    # they read 0 on exactly the jobs people most want to check.
                    # The real counts are operator-level, fetched below.
                )
            )

        # Only ask for live numbers on vertices that are actually running --
        # a FINISHED or CANCELED task has no subtasks left to sample.
        live = [x for x in out if x.status == "RUNNING"]
        if live:
            await asyncio.gather(
                *(self._vertex_live(c, job_id, x) for x in live),
                return_exceptions=True,
            )
        return out

    async def _vertex_live(
        self, c: httpx.AsyncClient, job_id: str, vertex: VertexHealth
    ) -> None:
        """Fills in backpressure, throughput and lag for one running vertex."""
        base = f"/jobs/{job_id}/vertices/{vertex.id}"

        async def backpressure() -> None:
            r = await c.get(f"{base}/backpressure")
            if r.status_code != 200:
                return
            d = r.json()
            if d.get("status") != "ok":
                return  # sampling still in progress
            vertex.backpressure_level = d.get("backpressureLevel")
            subtasks = d.get("subtasks") or []
            # The worst subtask is what matters: one wedged subtask stalls the
            # whole job, and averaging it away is how that gets missed.
            busy = [_float(s.get("busyRatio")) for s in subtasks]
            bp = [_float(s.get("ratio")) for s in subtasks]
            vertex.busy_ratio = _max(busy)
            vertex.backpressured_ratio = _max(bp)

        async def counts() -> None:
            """Cumulative records handled, from the operator-level metrics.

            Metric ids are "<subtask>.<operator>.<metric>", so a job with
            parallelism 4 and three chained operators reports twelve numbers for
            one logical count. Sum across subtasks, then take the busiest
            operator: in a chain that is the one that saw every record.
            """
            r = await c.get(f"{base}/metrics")
            if r.status_code != 200:
                return
            wanted = [
                m["id"]
                for m in r.json()
                if isinstance(m.get("id"), str)
                and m["id"].endswith(
                    (
                        ".numRecordsIn",
                        ".numRecordsOut",
                        ".numRecordsInPerSecond",
                        ".numRecordsOutPerSecond",
                    )
                )
            ]
            if not wanted:
                return
            r = await c.get(f"{base}/metrics", params={"get": ",".join(wanted[:200])})
            if r.status_code != 200:
                return

            totals: dict[tuple[str, str], float] = {}
            for m in r.json():
                mid = m.get("id", "")
                subtask, _, rest = mid.partition(".")
                operator, _, metric = rest.rpartition(".")
                value = _float(m.get("value"))
                if not operator or value is None:
                    continue
                if _is_committer(operator):
                    continue
                key = (operator, metric)
                totals[key] = totals.get(key, 0.0) + value

            def busiest(metric: str) -> float | None:
                values = [v for (_, m), v in totals.items() if m == metric]
                return max(values) if values else None

            total_in = busiest("numRecordsIn")
            total_out = busiest("numRecordsOut")
            if total_in is not None:
                vertex.records_in = int(total_in)
            if total_out is not None:
                vertex.records_out = int(total_out)
            vertex.records_in_rate = busiest("numRecordsInPerSecond")
            vertex.records_out_rate = busiest("numRecordsOutPerSecond")

        async def lag() -> None:
            # Kafka's lag metric is namespaced per subtask and operator, e.g.
            # "0.Source__foo[37].KafkaSourceReader.KafkaConsumer.records-lag-max",
            # so it cannot be requested by a plain name -- the ids have to be
            # discovered first.
            r = await c.get(f"{base}/metrics")
            if r.status_code != 200:
                return
            ids = [
                m["id"]
                for m in r.json()
                if isinstance(m.get("id"), str)
                and m["id"].endswith("records-lag-max")
            ]
            if not ids:
                return
            r = await c.get(f"{base}/metrics", params={"get": ",".join(ids[:64])})
            if r.status_code != 200:
                return
            vertex.kafka_lag_max = _max([_float(m.get("value")) for m in r.json()])

        await asyncio.gather(
            backpressure(), counts(), lag(), return_exceptions=True
        )


def _is_committer(operator: str) -> bool:
    """True for the commit stage of a two-phase sink.

    A committer emits exactly one record per checkpoint regardless of how much
    data moved, so it is the largest counter on an idle job: an untouched
    pipeline reported "134 records processed" purely because it had checkpointed
    134 times. It measures checkpoints, not throughput, and must not be counted
    as either.
    """
    return operator.endswith("Committer")


def _or(value: Any, fallback: Any) -> Any:
    """asyncio.gather(return_exceptions=True) hands back the exception itself."""
    return fallback if isinstance(value, BaseException) else value


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    """Parses a Flink metric value, rejecting the ones JSON cannot represent.

    Kafka reports "NaN" for lag whenever the consumer has not fetched recently.
    Letting that through produces a bare NaN token in the response body, which is
    not valid JSON and which the browser refuses to parse -- so the whole
    diagnostics panel would go blank because one metric was idle.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _max(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def _overview(j: dict[str, Any]) -> JobOverview:
    return JobOverview(
        job_id=j.get("jid", ""),
        name=j.get("name", ""),
        state=j.get("state", "UNKNOWN"),
        start_time=j.get("start-time"),
        end_time=j.get("end-time") if j.get("end-time", -1) > 0 else None,
        duration_ms=j.get("duration"),
    )
