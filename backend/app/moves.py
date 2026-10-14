"""Moving a job to another cluster, keeping its state.

A move is three steps MARS already knows how to do -- stop with a savepoint,
point the job at another cluster, resume from that savepoint -- done together,
checked first and undone if the last step fails, so a move never leaves a job
down. It needs both clusters to keep savepoints in one shared place ("job moves"
on the Clusters page), because the second cluster has to read what the first
one wrote.

Before anything is stopped, the destination must be reachable, have a free task
slot and run the same Flink version, and job moves must be ready between the two
clusters. A job that is not running only changes cluster, and only if the state
it would resume from is in the shared place.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from . import shared_storage, state_estimates
from .models import Job, RunState, Target
from .submitter import SubmissionError

log = logging.getLogger(__name__)

ACTIVE = (RunState.RUNNING.value, RunState.RESTARTING.value, RunState.SUBMITTING.value)

# One move per job at a time: a second click must not stop the job it is moving.
_moving: set[str] = set()


class MoveError(RuntimeError):
    pass


@dataclass
class Option:
    """A cluster this job could move to, or why not."""
    cluster: str
    ok: bool
    reasons: list[str] = field(default_factory=list)
    # Worth knowing, but not a reason to refuse: e.g. moving to a newer Flink.
    notes: list[str] = field(default_factory=list)
    # How much state moves and how long the job should be stopped for it.
    state_bytes: int | None = None
    pause_seconds: float | None = None
    rate_measured: bool = False


def _local(path: str) -> str:
    return shared_storage._local(path)


def _under(path: str | None, directory: str | None) -> bool:
    return bool(path and directory) and _local(path).startswith(_local(directory).rstrip("/") + "/")


async def _shared_dir(registry, db: Session, a: Target, b: Target) -> tuple[str | None, str]:
    """Where both clusters keep savepoints, if job moves are ready between them."""
    targets = {t.name: t for t in registry.all_enabled(db)}
    default = next((t for t in targets.values() if t.is_default), None)
    if default is None:
        return None, "There is no default cluster."
    dirs = {}
    for t in {a.name: a, b.name: b, default.name: default}.values():
        dirs[t.name], _ = await shared_storage.location(registry, t)
    records = shared_storage.recorded()
    # Job moves are set up between the default and each other cluster. Two other
    # clusters share a place when both are ready with the default on the same one.
    shared = None
    for t in (a, b):
        if t.is_default:
            continue
        m = shared_storage.job_moves(default.name, t.name, dirs, records)
        if m.state != "ready":
            return None, (f"Job moves are not set up for {t.name}. Set them up on the Clusters "
                          f"page first, so {b.name} can read the state {a.name} saves.")
        if shared is not None and shared != m.shared_dir:
            return None, f"{a.name} and {b.name} keep savepoints in different shared places."
        shared = m.shared_dir
    return shared, ""


async def state_of(db: Session, registry, job: Job) -> tuple[int | None, float | None, bool]:
    """(state bytes, expected pause in seconds, whether the speed was measured)."""
    run = next((r for r in job.runs if r.state in ACTIVE and r.flink_job_id), None)
    if run is None:
        return None, None, False
    try:
        size = await registry.cluster(registry.for_job(db, job)).state_size(run.flink_job_id)
    except Exception:
        return None, None, False
    r = state_estimates.rate(db)
    return size, state_estimates.expected_pause(size, r), r.measured


async def options(db: Session, registry, job: Job) -> list[Option]:
    current = registry.for_job(db, job)
    size, pause, measured = await state_of(db, registry, job)
    out = []
    for dest in registry.all_enabled(db):
        if dest.name == current.name:
            continue
        ok, reasons, notes = await _check(db, registry, job, current, dest)
        out.append(Option(dest.name, ok, reasons, notes, size, pause, measured))
    return out


def _version(v: str) -> tuple[int, ...]:
    parts = []
    for p in (v or "").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


async def _check(db: Session, registry, job: Job, src: Target, dest: Target
                 ) -> tuple[bool, list[str], list[str]]:
    reasons: list[str] = []
    notes: list[str] = []
    shared, why = await _shared_dir(registry, db, src, dest)
    if not shared:
        reasons.append(why)

    active = next((r for r in job.runs if r.state in ACTIVE), None)
    if active is not None and active.state != RunState.RUNNING.value:
        reasons.append(f"The job is {active.state}. Move it once it is running steadily.")
    if active is None and shared:
        point = job.restore_point
        if point is not None and not _under(point.path, shared):
            reasons.append(f"Its saved state is on {src.name}'s own disk ({point.path}), which "
                           f"{dest.name} cannot read. Run it here and stop it with state saved, "
                           f"then move it.")

    try:
        dest_info = await registry.cluster(dest).info()
    except Exception:
        reasons.append(f"{dest.name} is not answering.")
        return False, reasons, notes
    if active is not None and dest_info.slots_available < 1:
        reasons.append(f"{dest.name} has no free task slot.")
    try:
        src_info = await registry.cluster(src).info()
        here, there = _version(src_info.flink_version), _version(dest_info.flink_version)
        # Flink restores savepoints from older versions, not newer ones. So a move
        # onto a newer Flink -- the point of a rolling upgrade -- is allowed, and
        # said plainly, since the job cannot then come back.
        if there < here:
            reasons.append(f"{dest.name} runs Flink {dest_info.flink_version}, older than "
                           f"{src_info.flink_version} here. Flink cannot restore a savepoint "
                           f"onto an older version.")
        elif there > here:
            notes.append(f"Moves up from Flink {src_info.flink_version} to {dest_info.flink_version}. "
                         f"It cannot move back to {src.name} until that is upgraded too.")
    except Exception:
        if active is not None:
            reasons.append(f"{src.name}, where it runs now, is not answering.")
    return not reasons, reasons, notes


@dataclass
class MoveResult:
    moved: bool
    summary: str
    savepoint: str | None = None


async def move(db: Session, registry, job: Job, dest_name: str, user: str,
               native: bool = False) -> MoveResult:
    if job.name in _moving:
        raise MoveError(f"{job.name} is already being moved.")
    _moving.add(job.name)
    try:
        return await _move(db, registry, job, dest_name, user, native)
    finally:
        _moving.discard(job.name)


async def _move(db: Session, registry, job: Job, dest_name: str, user: str,
                native: bool = False) -> MoveResult:
    src = registry.for_job(db, job)
    dest = next((t for t in registry.all_enabled(db) if t.name == dest_name), None)
    if dest is None:
        raise MoveError(f"No enabled cluster named {dest_name}.")
    if dest.name == src.name:
        raise MoveError(f"{job.name} already runs on {dest.name}.")
    ok, reasons, _ = await _check(db, registry, job, src, dest)
    if not ok:
        raise MoveError(" ".join(reasons))
    shared, _ = await _shared_dir(registry, db, src, dest)
    new_target = None if dest.is_default else dest.name

    active = next((r for r in job.runs if r.state in ACTIVE), None)
    if active is None:
        job.target_name = new_target
        db.commit()
        log.info("%s moved %s to %s (not running)", user, job.name, dest.name)
        return MoveResult(True, f"{job.name} will run on {dest.name} when it is next started.")

    # 1. Stop with a savepoint. A failure leaves it running where it was.
    try:
        savepoint = await registry.submitter(src).stop_with_savepoint(db, active, native=native)
    except SubmissionError as exc:
        raise MoveError(f"Nothing was moved: {exc.summary}") from exc
    if not _under(savepoint, shared):
        # Configuration changed under us; resume where it was rather than strand it.
        await registry.submitter(src).submit(db, job, submitted_by=user, savepoint_path=savepoint)
        raise MoveError(f"The savepoint was written to {savepoint}, outside the shared {shared}, so "
                        f"{dest.name} could not read it. {job.name} was resumed on {src.name}.")

    # 2. and 3. Point it at the destination and resume there.
    job.target_name = new_target
    db.commit()
    try:
        await registry.submitter(dest).submit(db, job, submitted_by=user, savepoint_path=savepoint)
    except SubmissionError as exc:
        # Back where it was, with no await in between: the failed run on the
        # destination must not be picked up by the supervisor there first.
        job.target_name = None if src.is_default else src.name
        db.commit()
        try:
            await registry.submitter(src).submit(db, job, submitted_by=user, savepoint_path=savepoint)
        except SubmissionError as back:
            raise MoveError(f"{dest.name} could not start it ({exc.summary}), and resuming it on "
                            f"{src.name} failed too ({back.summary}). Its state is saved at "
                            f"{savepoint}; resume it from the job page.") from back
        raise MoveError(f"{dest.name} could not start it: {exc.summary} {job.name} is running "
                        f"on {src.name} again, from the savepoint just taken.") from exc
    log.info("%s moved %s from %s to %s via %s", user, job.name, src.name, dest.name, savepoint)
    return MoveResult(True, f"{job.name} now runs on {dest.name}, resumed from the savepoint "
                            f"taken on {src.name}.", savepoint)

