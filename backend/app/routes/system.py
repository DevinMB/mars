"""Cluster status and the connector catalogue."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import Principal
from ..db import get_session
from ..deps import current_principal, get_registry, get_targets
from ..registry import ConnectorRegistry
from ..schemas import ClusterOut
from ..targets import TargetRegistry

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/cluster", response_model=ClusterOut)
async def cluster_status(
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
    registry: TargetRegistry = Depends(get_targets),
) -> ClusterOut:
    """Capacity across every execution target, not just the default one.

    This used to read the configured cluster directly, which was right when there
    was only ever one. Once jobs can be placed on other targets, reporting the
    default's slots as though they were all of them understates the fleet -- the
    header read 3/12 with a second cluster registered and idle.
    """
    registry.ensure_default(db)
    db.commit()
    targets = registry.all_enabled(db)

    async def probe(t):
        try:
            return await registry.cluster(t).info()
        except Exception:
            return None

    infos = [i for i in await asyncio.gather(*(probe(t) for t in targets)) if i is not None]
    if not infos:
        return ClusterOut(reachable=False, targets_total=len(targets), targets_reachable=0)

    return ClusterOut(
        reachable=True,
        # Versions can differ across targets mid-upgrade; report one only when they agree.
        flink_version=infos[0].flink_version
        if len({i.flink_version for i in infos}) == 1
        else "mixed",
        taskmanagers=sum(i.taskmanagers for i in infos),
        slots_total=sum(i.slots_total for i in infos),
        slots_available=sum(i.slots_available for i in infos),
        jobs_running=sum(i.jobs_running for i in infos),
        targets_total=len(targets),
        targets_reachable=len(infos),
    )


@router.get("/connectors")
def list_connectors(
    kind: str | None = None,
    _: Principal = Depends(current_principal),
    registry: ConnectorRegistry = Depends(get_registry),
) -> list[dict]:
    """The manifests the console builds its source and sink forms from."""
    connectors = registry.for_kind(kind) if kind else registry.all()
    return [c.to_json() for c in connectors]


@router.get("/connectors/{identifier}")
def get_connector(
    identifier: str,
    _: Principal = Depends(current_principal),
    registry: ConnectorRegistry = Depends(get_registry),
) -> dict:
    from fastapi import HTTPException

    c = registry.get(identifier)
    if c is None:
        raise HTTPException(status_code=404, detail=f"No connector named '{identifier}'")
    return c.to_json()
