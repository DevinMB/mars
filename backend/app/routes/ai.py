"""The model MARS talks to. Administrators configure it; features consume it."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..ai import DEFAULT_BASE_URL, NEEDS_KEY, AiClient, AiConfig
from ..auth import Principal
from ..db import get_session
from ..deps import current_principal, get_secret_store, require_admin
from ..models import AiProvider, Secret
from ..schemas import AiProviderIn, AiProviderOut, AiStatusOut
from ..secrets import SecretError, SecretStore

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _row(db: Session) -> AiProvider:
    row = db.get(AiProvider, 1)
    if row is None:
        row = AiProvider(id=1)
        db.add(row)
        db.commit()
    return row


def config_for(db: Session, store: SecretStore, row: AiProvider | None = None) -> AiConfig:
    """Builds a usable config, decrypting the key only for this request."""
    row = row or _row(db)
    key = None
    if row.secret_name:
        try:
            key = store.reveal(db, row.secret_name)
        except SecretError:
            key = None
    return AiConfig(
        kind=row.kind,
        base_url=row.base_url,
        model=row.model,
        api_key=key,
        timeout_seconds=row.timeout_seconds,
    )


def _out(db: Session, store: SecretStore, row: AiProvider) -> AiProviderOut:
    return AiProviderOut(
        kind=row.kind,
        base_url=row.base_url,
        model=row.model,
        secret_name=row.secret_name,
        enabled=row.enabled,
        timeout_seconds=row.timeout_seconds,
        configured=row.enabled and config_for(db, store, row).configured,
        updated_by=row.updated_by,
    )


@router.get("", response_model=AiProviderOut)
def get_provider(
    # Readable by any signed-in user: features need to know whether AI is
    # available. No credential is exposed -- only the name of a secret.
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> AiProviderOut:
    return _out(db, store, _row(db))


@router.put("", response_model=AiProviderOut)
def set_provider(
    body: AiProviderIn,
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> AiProviderOut:
    if body.secret_name:
        exists = db.query(Secret).filter(Secret.name == body.secret_name).count()
        if not exists:
            raise HTTPException(
                status_code=400,
                detail=f"No secret named '{body.secret_name}'. Add it under Secrets first.",
            )
    if body.enabled and body.kind in NEEDS_KEY and not body.secret_name:
        raise HTTPException(
            status_code=400,
            detail=f"{body.kind} needs an API key. Store it under Secrets and select it here.",
        )
    if body.enabled and not body.model.strip():
        raise HTTPException(status_code=400, detail="Choose a model.")

    row = _row(db)
    row.kind = body.kind
    row.base_url = (body.base_url or DEFAULT_BASE_URL.get(body.kind, "")).rstrip("/")
    row.model = body.model.strip()
    row.secret_name = body.secret_name or None
    row.enabled = body.enabled
    row.timeout_seconds = max(5, min(body.timeout_seconds, 600))
    row.updated_by = principal.username
    db.commit()
    return _out(db, store, row)


@router.post("/test", response_model=AiStatusOut)
async def test_provider(
    body: AiProviderIn | None = None,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> AiStatusOut:
    """Probes the provider, optionally testing settings before they are saved."""
    if body is None:
        config = config_for(db, store)
    else:
        key = None
        if body.secret_name:
            try:
                key = store.reveal(db, body.secret_name)
            except SecretError:
                key = None
        config = AiConfig(
            kind=body.kind,
            base_url=body.base_url or DEFAULT_BASE_URL.get(body.kind, ""),
            model=body.model,
            api_key=key,
            timeout_seconds=body.timeout_seconds,
        )

    status = await AiClient(config).status()
    # A provider's error text can echo back a URL that carries a credential.
    return AiStatusOut(
        ok=status.ok,
        detail=store.redact(db, status.detail),
        models=status.models[:50],
    )
