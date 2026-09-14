"""Execution targets: the clusters jobs can be sent to."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Principal
from ..db import get_session
from ..deps import current_principal, get_targets, require_admin
from ..models import Job, Target
from ..schemas import TargetIn, TargetOut, TargetProbeIn, TargetProbeOut
from ..targets import TargetRegistry, labels_of

router = APIRouter(prefix="/api/targets", tags=["targets"])


def _out(db: Session, t: Target, live: dict | None = None) -> TargetOut:
    count = db.query(Job).filter(Job.target_name == t.name).count()
    if t.is_default:
        # Jobs that name no target run here, so they count against it.
        count += db.query(Job).filter(Job.target_name.is_(None)).count()
    return TargetOut(
        name=t.name,
        description=t.description,
        flink_rest_url=t.flink_rest_url,
        gateway_url=t.gateway_url,
        labels=labels_of(t),
        enabled=t.enabled,
        is_default=t.is_default,
        job_count=count,
        **(live or {}),
    )


@router.get("", response_model=list[TargetOut])
async def list_targets(
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
    registry: TargetRegistry = Depends(get_targets),
) -> list[TargetOut]:
    registry.ensure_default(db)
    db.commit()
    rows = list(db.scalars(select(Target).order_by(Target.name)))

    async def probe(t: Target) -> dict:
        try:
            info = await registry.cluster(t).info()
            return {
                "reachable": True,
                "flink_version": info.flink_version,
                "slots_total": info.slots_total,
                "slots_available": info.slots_available,
            }
        except Exception:
            # A target being down is information, not an error: the page should
            # still render and say which one is unreachable.
            return {"reachable": False}

    live = await asyncio.gather(*(probe(t) for t in rows))
    return [_out(db, t, l) for t, l in zip(rows, live)]


@router.post("/probe", response_model=TargetProbeOut)
async def probe_target(
    body: TargetProbeIn,
    # Admin-only, like the writes it precedes. This endpoint makes the server fetch
    # a URL the caller chose, so a lesser role could otherwise use it to probe the
    # internal network from inside it.
    _: Principal = Depends(require_admin),
    registry: TargetRegistry = Depends(get_targets),
) -> TargetProbeOut:
    """Checks a URL pair from the console before it is saved.

    Adding a cluster otherwise means saving a guess and finding out at the first
    submission. The two failures look different and are worth telling apart: an
    unreachable REST endpoint is usually a firewall or a wrong port, while a REST
    endpoint that answers alongside a gateway that does not usually means the
    gateway was never started.
    """
    import httpx

    from ..cluster import FlinkClusterClient

    flink_ok, flink_detail, version, slots = False, "", None, None
    try:
        info = await FlinkClusterClient(body.flink_rest_url.rstrip("/"), timeout=6).info()
        flink_ok, version, slots = True, info.flink_version, info.slots_total
        flink_detail = f"Flink {info.flink_version}, {info.slots_total} slots"
    except Exception as exc:
        flink_detail = _reason(exc)

    gateway_ok, gateway_detail = False, ""
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(body.gateway_url.rstrip("/") + "/v1/info")
            r.raise_for_status()
            gateway_ok = True
            gateway_detail = r.json().get("productName", "reachable")
    except Exception as exc:
        gateway_detail = _reason(exc)

    return TargetProbeOut(
        flink_ok=flink_ok, flink_detail=flink_detail,
        gateway_ok=gateway_ok, gateway_detail=gateway_detail,
        flink_version=version, slots_total=slots,
    )


def _reason(exc: Exception) -> str:
    """A sentence an operator can act on, rather than a class name."""
    text = str(exc) or exc.__class__.__name__
    lowered = text.lower()
    if "name or service not known" in lowered or "nodename nor servname" in lowered:
        return "Host not found. Check the hostname, or use an IP address."
    if "connection refused" in lowered:
        return "Connection refused. Nothing is listening on that port."
    if "timed out" in lowered or "timeout" in lowered:
        return "Timed out. Reachable names but no answer -- usually a firewall."
    return text[:160]


@router.post("", response_model=TargetOut, status_code=status.HTTP_201_CREATED)
def create_target(
    body: TargetIn,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
    registry: TargetRegistry = Depends(get_targets),
) -> TargetOut:
    if db.scalar(select(Target).where(Target.name == body.name)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"A target named '{body.name}' already exists.")
    target = Target(
        name=body.name,
        description=body.description,
        flink_rest_url=body.flink_rest_url.rstrip("/"),
        gateway_url=body.gateway_url.rstrip("/"),
        labels=json.dumps(body.labels),
        enabled=body.enabled,
    )
    db.add(target)
    db.flush()
    if body.is_default:
        _make_default(db, target)
    registry.ensure_default(db)
    db.commit()
    return _out(db, target)


@router.put("/{name}", response_model=TargetOut)
def update_target(
    name: str,
    body: TargetIn,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
    registry: TargetRegistry = Depends(get_targets),
) -> TargetOut:
    target = db.scalar(select(Target).where(Target.name == name))
    if target is None:
        raise HTTPException(status_code=404, detail=f"No target named '{name}'")
    if body.name != name:
        raise HTTPException(
            status_code=400,
            detail="A target cannot be renamed; jobs reference it by name. Create a "
                   "new one and repoint them.")

    target.description = body.description
    target.flink_rest_url = body.flink_rest_url.rstrip("/")
    target.gateway_url = body.gateway_url.rstrip("/")
    target.labels = json.dumps(body.labels)
    target.enabled = body.enabled
    if body.is_default:
        _make_default(db, target)
    elif target.is_default and not body.is_default:
        raise HTTPException(
            status_code=400,
            detail="Something must be the default. Make another target the default "
                   "instead of clearing this one.")
    # Pick up an edited URL without restarting the console.
    registry.forget(name)
    db.commit()
    return _out(db, target)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT,
               response_class=Response, response_model=None)
def delete_target(
    name: str,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
    registry: TargetRegistry = Depends(get_targets),
) -> None:
    target = db.scalar(select(Target).where(Target.name == name))
    if target is None:
        raise HTTPException(status_code=404, detail=f"No target named '{name}'")
    if target.is_default:
        raise HTTPException(status_code=400,
                            detail="The default target cannot be deleted.")

    users = [j.name for j in db.query(Job).filter(Job.target_name == name).all()]
    if users:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{name}' still runs: {', '.join(sorted(users))}. Repoint those jobs first.")

    db.delete(target)
    registry.forget(name)
    db.commit()


def _make_default(db: Session, target: Target) -> None:
    for other in db.scalars(select(Target).where(Target.is_default.is_(True))):
        other.is_default = False
    target.is_default = True
