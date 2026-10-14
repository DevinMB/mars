"""Bulk job actions: start one, watch it, stop it. The console does the work."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from .. import batches
from ..auth import Principal
from ..db import get_session
from ..deps import current_principal, get_targets, require_writer
from ..models import BatchOperation
from ..schemas import BatchIn, BatchItemOut, BatchOut
from ..targets import TargetRegistry

router = APIRouter(prefix="/api/batches", tags=["batches"])


def _out(b: BatchOperation) -> BatchOut:
    return BatchOut(
        id=b.id, kind=b.kind, cluster=b.cluster, status=b.status,
        native=bool(batches.options_of(b).get("native")),
        items=[BatchItemOut(job=i["job"], status=i["status"], note=i.get("note", ""))
               for i in batches.items_of(b)],
        created_by=b.created_by, created_at=b.created_at, finished_at=b.finished_at,
    )


@router.post("", response_model=BatchOut, status_code=status.HTTP_201_CREATED)
def start_batch(
    body: BatchIn,
    principal: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
    registry: TargetRegistry = Depends(get_targets),
) -> BatchOut:
    try:
        batch = batches.create(db, registry, body.kind, body.jobs, body.cluster, principal.username,
                               options={"native": body.native})
    except batches.BatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    batches.worker().wake()
    return _out(batch)


@router.get("/latest", response_model=BatchOut | None)
def latest_batch(
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
) -> BatchOut | None:
    """The running batch, else the most recent one, for the Jobs page to show."""
    b = batches.current(db) or db.query(BatchOperation).order_by(BatchOperation.id.desc()).first()
    return _out(b) if b else None


@router.get("/{batch_id}", response_model=BatchOut)
def get_batch(
    batch_id: int,
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
) -> BatchOut:
    b = db.get(BatchOperation, batch_id)
    if b is None:
        raise HTTPException(status_code=404, detail="No such bulk action.")
    return _out(b)


@router.post("/{batch_id}/stop", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def stop_batch(
    batch_id: int,
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
) -> Response:
    """Stops after the job in progress; that one finishes, the rest are left alone."""
    b = db.get(BatchOperation, batch_id)
    if b is None:
        raise HTTPException(status_code=404, detail="No such bulk action.")
    batches.request_stop(db, b)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
