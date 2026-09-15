"""The schema registry: configuring it, and reading schemas out of it."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import Principal
from ..db import get_session
from ..deps import current_principal, get_secret_store, require_admin, require_writer
from ..models import SchemaRegistry, Secret
from ..schemas import (
    RegistryOut,
    RegistryIn,
    RegistrySchemaOut,
    RegistryStatusOut,
    SchemaColumnOut,
)
from ..schemaregistry import AUTH_METHODS, RegistryClient, RegistryConfig, RegistryError
from ..secrets import SecretError, SecretStore

router = APIRouter(prefix="/api/schema-registry", tags=["schema registry"])


def _row(db: Session) -> SchemaRegistry:
    row = db.get(SchemaRegistry, 1)
    if row is None:
        row = SchemaRegistry(id=1)
        db.add(row)
        db.commit()
    return row


def config_for(
    db: Session, store: SecretStore, row: SchemaRegistry | None = None
) -> RegistryConfig:
    row = row or _row(db)
    credential = None
    if row.secret_name:
        try:
            credential = store.reveal(db, row.secret_name)
        except SecretError:
            credential = None
    return RegistryConfig(
        url=row.url,
        auth_method=row.auth_method,
        username=row.username,
        credential=credential,
        timeout_seconds=row.timeout_seconds,
    )


def _out(db: Session, store: SecretStore, row: SchemaRegistry) -> RegistryOut:
    return RegistryOut(
        url=row.url,
        auth_method=row.auth_method,
        username=row.username,
        secret_name=row.secret_name,
        enabled=row.enabled,
        timeout_seconds=row.timeout_seconds,
        configured=row.enabled and config_for(db, store, row).configured,
        updated_by=row.updated_by,
    )


@router.get("", response_model=RegistryOut)
def get_registry_settings(
    # Readable by anyone signed in: the catalog editor has to know whether to
    # offer schema lookup at all. No credential is exposed, only a secret's name.
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> RegistryOut:
    return _out(db, store, _row(db))


@router.put("", response_model=RegistryOut)
def set_registry_settings(
    body: RegistryIn,
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> RegistryOut:
    if body.auth_method not in AUTH_METHODS:
        raise HTTPException(
            status_code=400,
            detail=f"auth_method must be one of: {', '.join(AUTH_METHODS)}",
        )
    if body.secret_name:
        if not db.query(Secret).filter(Secret.name == body.secret_name).count():
            raise HTTPException(
                status_code=400,
                detail=f"No secret named '{body.secret_name}'. Add it under Secrets first.",
            )
    if body.enabled and body.auth_method != "none" and not body.secret_name:
        raise HTTPException(
            status_code=400,
            detail=f"'{body.auth_method}' authentication needs a credential from the secret store.",
        )
    if body.enabled and not body.url.strip():
        raise HTTPException(status_code=400, detail="Give the registry's address.")

    row = _row(db)
    row.url = body.url.strip().rstrip("/")
    row.auth_method = body.auth_method
    row.username = body.username.strip()
    row.secret_name = body.secret_name or None
    row.enabled = body.enabled
    row.timeout_seconds = max(2, min(body.timeout_seconds, 120))
    row.updated_by = principal.username
    db.commit()
    return _out(db, store, row)


@router.post("/test", response_model=RegistryStatusOut)
async def test_registry(
    body: RegistryIn | None = None,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> RegistryStatusOut:
    """Probes the registry, optionally testing settings before they are saved."""
    if body is None:
        config = config_for(db, store)
    else:
        credential = None
        if body.secret_name:
            try:
                credential = store.reveal(db, body.secret_name)
            except SecretError:
                credential = None
        config = RegistryConfig(
            url=body.url, auth_method=body.auth_method, username=body.username,
            credential=credential, timeout_seconds=body.timeout_seconds,
        )

    ok, detail = await RegistryClient(config).check()
    return RegistryStatusOut(ok=ok, detail=store.redact(db, detail))


@router.get("/subjects")
async def list_subjects(
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> list[str]:
    try:
        return await RegistryClient(config_for(db, store)).subjects()
    except RegistryError as exc:
        raise HTTPException(status_code=502, detail=store.redact(db, str(exc))) from exc


@router.get("/subjects/{subject}", response_model=RegistrySchemaOut)
async def get_subject_schema(
    subject: str,
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> RegistrySchemaOut:
    """The latest schema for a subject, as the columns a table should declare."""
    try:
        result = await RegistryClient(config_for(db, store)).latest(subject)
    except RegistryError as exc:
        raise HTTPException(status_code=502, detail=store.redact(db, str(exc))) from exc

    return RegistrySchemaOut(
        subject=result.subject,
        version=result.version,
        schema_id=result.schema_id,
        columns=[
            SchemaColumnOut(name=c.name, sqlType=c.sql_type, note=c.note)
            for c in result.columns
        ],
        warnings=result.warnings,
    )
