"""Cluster status and the connector catalogue."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import Principal
from ..cluster import FlinkClusterClient
from ..deps import current_principal, get_cluster, get_registry
from ..registry import ConnectorRegistry
from ..schemas import ClusterOut

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/cluster", response_model=ClusterOut)
async def cluster_status(
    _: Principal = Depends(current_principal),
    cluster: FlinkClusterClient = Depends(get_cluster),
) -> ClusterOut:
    try:
        info = await cluster.info()
    except Exception:
        # The console must still render when Flink is down; it just says so.
        return ClusterOut(reachable=False)
    return ClusterOut(
        reachable=True,
        flink_version=info.flink_version,
        taskmanagers=info.taskmanagers,
        slots_total=info.slots_total,
        slots_available=info.slots_available,
        jobs_running=info.jobs_running,
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
