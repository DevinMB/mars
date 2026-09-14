"""Secret management. Values go in and are never returned."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..auth import Principal
from ..db import get_session
from ..deps import get_secret_store, require_admin, require_writer
from ..models import CatalogEntry, Job, Secret
from ..schemas import SecretIn, SecretOut
from ..secrets import SecretError, SecretStore

router = APIRouter(prefix="/api/secrets", tags=["secrets"])


@router.get("", response_model=list[SecretOut])
def list_secrets(
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
) -> list[SecretOut]:
    rows = db.query(Secret).order_by(Secret.name).all()
    return [
        SecretOut(
            name=r.name,
            description=r.description,
            created_by=r.created_by,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.put("/{name}", response_model=SecretOut, status_code=status.HTTP_200_OK)
def put_secret(
    name: str,
    body: SecretIn,
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> SecretOut:
    if body.name != name:
        raise HTTPException(status_code=400, detail="Name in path and body must match.")
    try:
        row = store.put(db, name, body.value, body.description, created_by=principal.username)
    except SecretError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return SecretOut(
        name=row.name,
        description=row.description,
        created_by=row.created_by,
        updated_at=row.updated_at,
    )


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_secret(
    name: str,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> None:
    # Deleting a secret a job depends on breaks that job at its next submission,
    # with an error that points at a missing secret rather than the deletion.
    ref = "${secret:%s}" % name
    users = [e.name for e in db.query(CatalogEntry).all() if ref in e.sql_text]
    users += [j.name for j in db.query(Job).all() if ref in j.sql_text]
    if users:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Secret '{name}' is still referenced by: {', '.join(sorted(set(users)))}. "
                f"Update those first."
            ),
        )

    if not store.delete(db, name):
        raise HTTPException(status_code=404, detail=f"No secret named '{name}'")
    db.commit()
