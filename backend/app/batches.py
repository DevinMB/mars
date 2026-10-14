"""Bulk job actions, worked through by the console in the background.

Moving every job to another cluster is a maintenance step, and it must not
depend on the browser that started it: a laptop that sleeps or restarts for an
update would otherwise leave half the jobs moved and the rest never asked for.
So a batch is a row in the database and this worker runs it, one job at a time,
recording each job's result as it goes. Anyone can watch it from the Jobs page.

One batch at a time. Each step checks the job's state when it runs rather than
trusting the plan made at the start, which is what makes a batch safe to pick up
again after the console restarts mid-way (a deploy, say):

* move: a job already on the destination counts as done; one interrupted mid-move
  (stopped, not yet started) is resumed there.
* stop: a job that is not running is skipped.
* resume: a job that is running is skipped.

A move stops at the first job that cannot move -- that job is already back where
it was, and the cause (no free slots, say) usually applies to the rest. Stops and
resumes carry on past a failure, since each job is independent.
"""
from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy.orm import Session

from . import moves
from .db import session_scope
from .models import BatchOperation, Job, RunState, utcnow
from .submitter import SubmissionError

log = logging.getLogger(__name__)

KINDS = ("move", "stop", "resume")
OPEN = ("running", "stopping")
ACTIVE = (RunState.RUNNING.value, RunState.RESTARTING.value, RunState.SUBMITTING.value)


class BatchError(RuntimeError):
    pass


def _active(job: Job) -> bool:
    return any(r.state in ACTIVE for r in job.runs)


def items_of(batch: BatchOperation) -> list[dict]:
    try:
        return json.loads(batch.items or "[]")
    except json.JSONDecodeError:
        return []


def _save(db: Session, batch: BatchOperation, items: list[dict]) -> None:
    batch.items = json.dumps(items)
    db.commit()


def current(db: Session) -> BatchOperation | None:
    return db.query(BatchOperation).filter(BatchOperation.status.in_(OPEN)).first()


def options_of(batch: BatchOperation) -> dict:
    try:
        return json.loads(batch.options or "{}")
    except json.JSONDecodeError:
        return {}


def create(db: Session, registry, kind: str, job_names: list[str], cluster: str | None,
           user: str, options: dict | None = None) -> BatchOperation:
    if kind not in KINDS:
        raise BatchError(f"Unknown action '{kind}'.")
    if current(db) is not None:
        raise BatchError("Another bulk action is still running. Wait for it to finish, or stop it.")
    names = list(dict.fromkeys(job_names))
    if not names:
        raise BatchError("Select at least one job.")
    jobs = {j.name: j for j in db.query(Job).filter(Job.name.in_(names))}
    missing = [n for n in names if n not in jobs]
    if missing:
        raise BatchError(f"No job named {', '.join(missing)}.")
    if kind == "move":
        if not cluster or cluster not in {t.name for t in registry.all_enabled(db)}:
            raise BatchError("Choose a cluster to move the jobs to.")
    else:
        cluster = None
    items = [{"job": n, "was_running": _active(jobs[n]), "status": "waiting", "note": ""} for n in names]
    batch = BatchOperation(kind=kind, cluster=cluster, status="running",
                           items=json.dumps(items), created_by=user,
                           options=json.dumps({"native": bool((options or {}).get("native"))}))
    db.add(batch)
    db.commit()
    log.info("%s started a bulk %s of %d job(s)%s", user, kind, len(names),
             f" to {cluster}" if cluster else "")
    return batch


def request_stop(db: Session, batch: BatchOperation) -> None:
    if batch.status == "running":
        batch.status = "stopping"
        db.commit()


# How long a moved job gets to prove itself healthy: a few checkpoint intervals,
# at least this, never more than the ceiling.
HEALTH_FLOOR_SECONDS = 90.0
HEALTH_CEILING_SECONDS = 15 * 60.0


async def healthy(db: Session, registry, job: Job, sleep=asyncio.sleep) -> str | None:
    """None when the job runs on its cluster and has completed a checkpoint since
    it started there; otherwise what is wrong.

    Running is not enough: a job can be RUNNING and stuck, unable to reach a
    sink or restore its state, and moving the next job before knowing would
    spread the damage. A completed checkpoint means it restored and makes
    progress. A job without checkpointing is judged on staying RUNNING.
    """
    run = next((r for r in job.runs if r.state in ACTIVE and r.flink_job_id), None)
    if run is None:
        return "It is not running after the move."
    cluster = registry.cluster(registry.for_job(db, job))
    waited, limit = 0.0, HEALTH_FLOOR_SECONDS
    while True:
        try:
            overview = await cluster.get_job(run.flink_job_id)
            health = await cluster.checkpoint_health(run.flink_job_id)
        except Exception:
            overview, health = None, None
        if overview is not None and overview.state in ("FAILED", "CANCELED", "FINISHED"):
            return f"It stopped on {registry.for_job(db, job).name} ({overview.state.lower()}) after the move."
        if health is not None:
            if health.interval_ms:
                limit = min(HEALTH_CEILING_SECONDS, max(HEALTH_FLOOR_SECONDS, 3 * health.interval_ms / 1000))
            if overview is not None and overview.state == "RUNNING":
                if health.completed > 0:
                    return None
                if not health.interval_ms and waited >= 30:
                    return None  # no checkpointing: running steadily is all there is
        if waited >= limit:
            where = registry.for_job(db, job).name
            return (f"It runs on {where} but completed no checkpoint in {limit / 60:.0f} minutes, so it "
                    f"may not be making progress. The batch stopped here so you can look.")
        await sleep(5)
        waited += 5


async def _do(db: Session, registry, batch: BatchOperation, item: dict) -> tuple[str, str]:
    """Runs one job's step; returns (status, note)."""
    job = db.query(Job).filter(Job.name == item["job"]).first()
    if job is None:
        return "failed", "This job no longer exists."
    user = batch.created_by or "batch"

    async def resume(where: str) -> str:
        point = job.restore_point
        await registry.for_job_submitter(db, job).submit(
            db, job, submitted_by=user, savepoint_path=point.path if point else None)
        return f"Resumed on {where}"

    if batch.kind == "move":
        dest = batch.cluster
        here = registry.for_job(db, job).name
        if here == dest:
            if item.get("was_running") and not _active(job):
                return "done", await resume(dest) + ", finishing a move the console was interrupted in."
            return "skipped", f"Already on {dest}."
        result = await moves.move(db, registry, job, dest, user,
                                  native=options_of(batch).get("native", False))
        db.expire(job)
        note = result.summary
        if item.get("interrupted") and item.get("was_running") and not _active(job):
            # Stopped before the console restarted, so the move only re-pointed it.
            note = await resume(dest) + ", finishing a move the console was interrupted in."
            db.expire(job)
        if item.get("was_running"):
            problem = await healthy(db, registry, job)
            if problem:
                return "failed", problem
            note += " Checkpointing there."
        return "done", note

    if batch.kind == "stop":
        run = next((r for r in job.runs if r.state in ACTIVE), None)
        if run is None:
            return "skipped", "Not running."
        await registry.for_job_submitter(db, job).stop_with_savepoint(
            db, run, native=options_of(batch).get("native", False))
        return "done", "Stopped with its state saved."

    if _active(job):
        return "skipped", "Already running."
    return "done", await resume(registry.for_job(db, job).name) + "."


async def run(batch_id: int, registry) -> None:
    with session_scope() as db:
        batch = db.get(BatchOperation, batch_id)
        if batch is None or batch.status not in OPEN:
            return
        items = items_of(batch)
        # A job still marked working was mid-step when the console stopped.
        for item in items:
            if item["status"] == "working":
                item["status"], item["interrupted"] = "waiting", True
        _save(db, batch, items)
        # A move that already failed before a restart still halts the rest.
        halted = batch.kind == "move" and any(it["status"] == "failed" for it in items)

    for i in range(len(items)):
        with session_scope() as db:
            batch = db.get(BatchOperation, batch_id)
            items = items_of(batch)
            item = items[i]
            if item["status"] != "waiting":
                continue
            if halted or batch.status == "stopping":
                item["status"] = "notrun"
                item["note"] = ("Not attempted after the failure above." if halted
                                else "Not attempted: the batch was stopped.")
                _save(db, batch, items)
                continue
            item["status"] = "working"
            _save(db, batch, items)
            try:
                status, note = await _do(db, registry, batch, item)
            except (moves.MoveError, SubmissionError) as exc:
                status, note = "failed", getattr(exc, "summary", None) or str(exc)
            except Exception as exc:  # one job's surprise must not strand the batch
                log.exception("Bulk %s of %s failed", batch.kind, item["job"])
                status, note = "failed", f"Unexpected error: {exc}"
            db.rollback()
            batch = db.get(BatchOperation, batch_id)
            items = items_of(batch)
            items[i].update(status=status, note=note)
            items[i].pop("interrupted", None)
            _save(db, batch, items)
            if status == "failed" and batch.kind == "move":
                halted = True

    with session_scope() as db:
        batch = db.get(BatchOperation, batch_id)
        items = items_of(batch)
        if any(it["status"] == "notrun" and "stopped" in it["note"] for it in items):
            batch.status = "stopped"
        elif halted:
            batch.status = "failed"
        else:
            batch.status = "done"
        batch.finished_at = utcnow()
        log.info("Bulk %s %s: %s", batch.kind, batch.id, batch.status)


class BatchWorker:
    """Runs open batches, one at a time, in the console's own process."""

    def __init__(self, registry, poll_seconds: float = 3.0) -> None:
        self._registry = registry
        self._poll = poll_seconds
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="mars-batches")

    def wake(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                with session_scope() as db:
                    batch = current(db)
                    batch_id = batch.id if batch else None
                if batch_id is not None:
                    await run(batch_id, self._registry)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Bulk action worker failed; trying again shortly")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll)
            except asyncio.TimeoutError:
                pass


_worker: BatchWorker | None = None


def worker(registry=None) -> BatchWorker:
    global _worker
    if _worker is None:
        if registry is None:
            from .deps import get_targets
            registry = get_targets()
        _worker = BatchWorker(registry)
    return _worker
