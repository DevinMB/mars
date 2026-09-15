"""Export and import definitions, for recovery and for review."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..auth import Principal
from ..db import get_session
from ..deps import get_secret_store, require_admin, require_writer
from ..portability import export_all, import_all, parse, to_yaml
from ..schemas import ImportRequest, ImportResult
from ..secrets import SecretStore

router = APIRouter(prefix="/api", tags=["portability"])


@router.get("/export")
def export_definitions(
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> Response:
    """Every definition, as YAML. Secret values are deliberately not included."""
    body = to_yaml(export_all(db, store))
    return Response(
        content=body,
        media_type="application/yaml",
        headers={"Content-Disposition": 'attachment; filename="mars-export.yaml"'},
    )


@router.post("/import", response_model=ImportResult)
def import_definitions(
    body: ImportRequest,
    # Administrator rather than writer: this overwrites definitions that jobs are
    # running from, across the whole installation at once.
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> ImportResult:
    try:
        payload = parse(body.yaml_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    outcome = import_all(
        db, store, payload, dry_run=body.dry_run, replace=body.replace
    )
    return ImportResult(
        dry_run=outcome.dry_run,
        ok=outcome.ok,
        created=outcome.created,
        updated=outcome.updated,
        unchanged=outcome.unchanged,
        skipped=outcome.skipped,
        errors=outcome.errors,
        missing_secrets=outcome.missing_secrets,
    )
