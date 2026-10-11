"""Scheduling, in two modes.

**cron** fires a bounded job on a schedule -- backfills, nightly reports.

**supervisor** keeps a streaming job running. This is the mode that matters for
stream processing: Flink restarts a job's *tasks* on failure, but a job that has
exhausted its restart strategy stays dead, and nothing in Flink brings it back.
MARS notices and resubmits.

Both modes refuse to start a second copy of a job that is already running. For a
sink with deterministic ids a duplicate run merely wastes effort; for a Kafka sink
it writes every record twice.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from .db import session_scope
from .metrics import SUPERVISOR_RESUBMISSIONS
from .models import Job, RunState, Schedule, ScheduleMode, utcnow
from .submitter import JobSubmitter, SubmissionError
from .targets import TargetRegistry, UnknownTargetError

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        submitter: JobSubmitter,
        targets: TargetRegistry | None = None,
        tick_seconds: int = 20,
    ) -> None:
        self._submitter = submitter
        self._targets = targets
        self._tick = tick_seconds
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self._loop(), name="mars-scheduler")
            log.info("Scheduler started (tick %ss)", self._tick)

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A scheduler that dies on one bad job is worse than one that
                # logs and carries on.
                log.exception("Scheduler tick failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._tick)
            except asyncio.TimeoutError:
                pass

    async def tick(self) -> None:
        """One pass: reconcile run states, then act on due schedules."""
        with session_scope() as db:
            await self._reconcile(db)

        with session_scope() as db:
            schedules = (
                db.query(Schedule).filter(Schedule.enabled.is_(True)).all()
            )
            due: list[tuple[int, str]] = []
            for sched in schedules:
                job = db.get(Job, sched.job_id)
                if job is None or not job.enabled:
                    continue
                if self._should_fire(db, sched, job):
                    due.append((job.id, sched.mode))
                if sched.mode == ScheduleMode.CRON.value and sched.cron_expr:
                    sched.next_fire_at = _next_fire(sched)

        for job_id, mode in due:
            await self._fire(job_id, mode)

    async def _reconcile(self, db) -> None:
        """Asks each cluster about the jobs placed on it.

        One query per target rather than one for everything: a run belongs to the
        cluster its job names, and asking the wrong cluster returns "no such job",
        which would mark a healthy run as lost.
        """
        if self._targets is None:
            await self._submitter.refresh_states(db)
            return

        default = self._targets.ensure_default(db)
        for target in self._targets.all_enabled(db):
            submitter = self._targets.submitter(target)
            try:
                await submitter.refresh_states(db, target_name=target.name)
                if target.id == default.id:
                    # Jobs that name no target run on the default one.
                    await submitter.refresh_states(db, target_name=None)
            except Exception as exc:
                log.warning("Could not reconcile target '%s': %s", target.name, exc)

    def _should_fire(self, db, sched: Schedule, job: Job) -> bool:
        if _is_active(job):
            # Supervisor mode: still running, nothing to do. Cron mode: the
            # previous run has not finished, so skip rather than overlap.
            return False

        if sched.mode == ScheduleMode.SUPERVISOR.value:
            # Only resurrect something that has actually run and stopped; never
            # auto-start a job a user has not run yet.
            last = job.runs[0] if job.runs else None
            return last is not None and last.state in (
                RunState.FAILED.value,
                RunState.FINISHED.value,
            )

        if not sched.cron_expr:
            return False

        now = _now_in(sched.timezone_name)
        reference = sched.last_fire_at or sched.created_at
        if reference is None:
            return False
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        try:
            nxt = croniter(sched.cron_expr, reference.astimezone(_zone(sched.timezone_name))).get_next(datetime)
        except (ValueError, KeyError):
            log.error("Job '%s' has an invalid cron expression: %s", job.name, sched.cron_expr)
            return False
        return nxt <= now

    async def _fire(self, job_id: int, mode: str) -> None:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            if _is_active(job):
                return

            submitter = self._submitter
            if self._targets is not None:
                try:
                    submitter = self._targets.for_job_submitter(db, job)
                except UnknownTargetError as exc:
                    log.error("Scheduler cannot place job '%s': %s", job.name, exc)
                    return
            try:
                # Supervising a stateful job means putting it back as it was, not
                # merely running it again: restarting from empty state loses a
                # half-finished window or a running count without saying so.
                # The newest restore point, not the newest savepoint: after a
                # crash the last savepoint can be days old, and resuming from it
                # replays everything since into the sinks.
                # Cron jobs are bounded and deliberately start clean each time.
                point = (
                    job.restore_point
                    if mode == ScheduleMode.SUPERVISOR.value
                    else None
                )
                if mode == ScheduleMode.SUPERVISOR.value:
                    SUPERVISOR_RESUBMISSIONS.labels(mars_job=job.name).inc()
                await submitter.submit(
                    db, job, submitted_by="scheduler", by_schedule=True,
                    savepoint_path=point.path if point else None,
                )
                log.info(
                    "Scheduler started job '%s' (%s)%s",
                    job.name, mode,
                    f" from {point.kind} {point.path}" if point else "",
                )
            except SubmissionError as exc:
                # The failure is already recorded against a JobRun; the schedule
                # stays enabled so a transient outage self-heals.
                log.error("Scheduler could not start job '%s': %s", job.name, exc)

            if job.schedule is not None:
                job.schedule.last_fire_at = utcnow()
                if job.schedule.mode == ScheduleMode.CRON.value:
                    job.schedule.next_fire_at = _next_fire(job.schedule)


def _is_active(job: Job) -> bool:
    # A restarting job still holds its slot; resubmitting would give the cluster
    # two copies of a job that is already struggling.
    return any(
        r.state
        in (
            RunState.RUNNING.value,
            RunState.SUBMITTING.value,
            RunState.RESTARTING.value,
        )
        for r in job.runs
    )


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _now_in(tz_name: str) -> datetime:
    return datetime.now(_zone(tz_name))


def _next_fire(sched: Schedule) -> datetime | None:
    if not sched.cron_expr:
        return None
    try:
        return croniter(sched.cron_expr, _now_in(sched.timezone_name)).get_next(datetime)
    except (ValueError, KeyError):
        return None
