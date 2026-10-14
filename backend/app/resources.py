"""Where a cluster's memory, CPU and slots go.

The job page explains one job; this answers the question a cluster raises first:
which jobs are using it. For each MARS job running on the cluster: the slots it
holds (its widest operator, since operators share slots), its state (what a
savepoint writes and a heap backend holds in memory), how long its checkpoints
take, and how busy its busiest operator is -- the one that sets its pace.
"""
from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session

from .models import Job, RunState, Target

ACTIVE = (RunState.RUNNING.value, RunState.RESTARTING.value)


async def footprint(cluster, job: Job, flink_job_id: str) -> dict:
    out = {"job": job.name, "slots": None, "state_bytes": None, "checkpoint_ms": None,
           "busiest": None, "busy_ratio": None, "available": False}
    try:
        detail = await cluster.job_detail(flink_job_id)
    except Exception:
        return out
    if detail is None:
        return out
    out["available"] = True
    if detail.vertices:
        out["slots"] = max((v.parallelism or 0) for v in detail.vertices) or None
        busy = [v for v in detail.vertices if v.busy_ratio is not None]
        if busy:
            top = max(busy, key=lambda v: v.busy_ratio)
            out["busiest"], out["busy_ratio"] = top.name, top.busy_ratio
    out["state_bytes"] = detail.checkpoints.latest_completed_size_bytes
    out["checkpoint_ms"] = detail.checkpoints.latest_completed_duration_ms
    return out


async def cluster_resources(db: Session, registry, target: Target) -> dict:
    cluster = registry.cluster(target)
    machines = await cluster.resources()
    placed = []
    for job in db.query(Job).order_by(Job.name):
        if registry.for_job(db, job).name != target.name:
            continue
        run = next((r for r in job.runs if r.state in ACTIVE and r.flink_job_id), None)
        if run is not None:
            placed.append((job, run.flink_job_id))
    jobs = await asyncio.gather(*(footprint(cluster, j, fid) for j, fid in placed))
    # Heaviest first: most state, then most slots.
    jobs = sorted(jobs, key=lambda j: (-(j["state_bytes"] or 0), -(j["slots"] or 0), j["job"]))
    return {"cluster": target.name, **machines, "jobs": jobs}
