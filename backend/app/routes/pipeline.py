"""The pipeline: jobs connected through the topics and tables they share."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .. import lineage
from ..auth import Principal
from ..db import get_session
from ..deps import current_principal, get_registry, require_writer
from ..models import CatalogEntry, ExternalEndpoint
from ..registry import ConnectorRegistry

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


class ExternalIn(BaseModel):
    resource_key: str = Field(min_length=1, max_length=512)
    name: str = Field(min_length=1, max_length=128)
    direction: str
    note: str | None = Field(default=None, max_length=512)

    @field_validator("direction")
    @classmethod
    def _direction(cls, v: str) -> str:
        if v not in ("produces", "consumes"):
            raise ValueError("direction must be 'produces' or 'consumes'")
        return v


@router.get("")
def pipeline(
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
    registry: ConnectorRegistry = Depends(get_registry),
) -> dict:
    return lineage.pipeline_graph(db, registry)


@router.post("/external", status_code=status.HTTP_201_CREATED)
def add_external(
    body: ExternalIn,
    principal: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
    registry: ConnectorRegistry = Depends(get_registry),
) -> dict:
    """Declares something outside Flink that writes or reads a topic or table."""
    known = {lineage.resource_of(e, registry).key for e in db.query(CatalogEntry)}
    if body.resource_key not in known:
        raise HTTPException(status_code=404, detail="No catalog entry points at that topic or table.")
    ext = ExternalEndpoint(resource_key=body.resource_key, name=body.name.strip(),
                           direction=body.direction, note=(body.note or "").strip() or None,
                           created_by=principal.username)
    db.add(ext)
    db.commit()
    return {"id": ext.id}


@router.delete("/external/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT,
               response_class=Response, response_model=None)
def remove_external(
    endpoint_id: int,
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
) -> None:
    ext = db.get(ExternalEndpoint, endpoint_id)
    if ext is None:
        raise HTTPException(status_code=404, detail="No such producer or consumer.")
    db.delete(ext)
    db.commit()
