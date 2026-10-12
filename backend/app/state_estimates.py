"""How long saving and restoring a job's state should take, from what was seen.

A savepoint writes the job's whole state and a restore reads it back, so both
scale with its size. Waiting a fixed three minutes was fine for state measured in
kilobytes and wrong for anything large: a 100 GB savepoint was reported failed
while Flink was still writing it, and Flink then stopped the job anyway.

The rate is measured, not assumed: each savepoint MARS takes records its size and
how long it took, and the median of recent large ones is this installation's real
speed (network, storage, serialization together). Until there are any, a
conservative 50 MB/s stands in -- roughly gigabit NFS with canonical
serialization at parallelism 1.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from sqlalchemy.orm import Session

from .models import JobRun

ASSUMED_RATE = 50 * 1024 * 1024  # bytes per second
# Small savepoints are dominated by fixed overhead and say nothing about speed.
_MEASURABLE = 64 * 1024 * 1024
FLOOR_SECONDS = 180.0  # what a small job always got
CEILING_SECONDS = 12 * 3600.0
# Stopping, scheduling and starting a job cost seconds whatever its size.
OVERHEAD_SECONDS = 5.0


@dataclass
class Rate:
    bytes_per_second: float
    measured: bool  # from this installation's savepoints, not the assumption


def rate(db: Session) -> Rate:
    runs = (
        db.query(JobRun)
        .filter(JobRun.savepoint_bytes >= _MEASURABLE, JobRun.savepoint_ms > 0)
        .order_by(JobRun.id.desc())
        .limit(20)
        .all()
    )
    if not runs:
        return Rate(ASSUMED_RATE, measured=False)
    return Rate(median(r.savepoint_bytes / (r.savepoint_ms / 1000) for r in runs), measured=True)


def savepoint_budget(size_bytes: int | None, r: Rate) -> float:
    """How long to wait for a savepoint before giving up: generous, because
    giving up on one Flink is still writing helps no one."""
    if not size_bytes:
        return FLOOR_SECONDS
    return max(FLOOR_SECONDS, min(CEILING_SECONDS, 3 * size_bytes / r.bytes_per_second + 120))


def expected_pause(size_bytes: int | None, r: Rate) -> float:
    """Seconds a job is stopped while it moves: its state written, then read."""
    if not size_bytes:
        return OVERHEAD_SECONDS
    return OVERHEAD_SECONDS + 2 * size_bytes / r.bytes_per_second
