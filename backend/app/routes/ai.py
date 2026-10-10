"""The model MARS talks to. Administrators configure it; features consume it."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..ai import DEFAULT_BASE_URL, AiClient, AiConfig
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
        auth_method=row.auth_method,
        auth_header=row.auth_header,
        auth_username=row.auth_username,
        extra_headers=_headers_of(row.extra_headers),
        temperature=row.temperature,
        max_tokens=row.max_tokens,
    )


def _headers_of(raw: str | None) -> dict[str, str]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}


def _out(db: Session, store: SecretStore, row: AiProvider) -> AiProviderOut:
    return AiProviderOut(
        kind=row.kind,
        base_url=row.base_url,
        model=row.model,
        secret_name=row.secret_name,
        enabled=row.enabled,
        timeout_seconds=row.timeout_seconds,
        auth_method=row.auth_method,
        auth_header=row.auth_header,
        auth_username=row.auth_username,
        extra_headers=_headers_of(row.extra_headers),
        temperature=row.temperature,
        max_tokens=row.max_tokens,
        configured=row.enabled and config_for(db, store, row).configured,
        updated_by=row.updated_by,
    )


@router.get("", response_model=AiProviderOut)
def get_provider(
    # Features need availability; only administrators need custom header values.
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> AiProviderOut:
    result = _out(db, store, _row(db))
    if not principal.is_admin():
        result.extra_headers = {}
    return result


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
    if body.enabled and body.auth_method != "none" and not body.secret_name:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{body.auth_method}' authentication needs a credential. Store it "
                f"under Secrets and select it here."
            ),
        )
    if body.enabled and body.auth_method == "header" and not body.auth_header.strip():
        raise HTTPException(
            status_code=400,
            detail="Name the header the credential should be sent in, for example x-api-key.",
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
    row.auth_method = body.auth_method
    row.auth_header = body.auth_header.strip()
    row.auth_username = body.auth_username.strip()
    row.extra_headers = json.dumps(
        {k.strip(): v for k, v in body.extra_headers.items() if k.strip()}
    )
    row.temperature = body.temperature
    row.max_tokens = max(1, min(body.max_tokens, 32000))
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
            auth_method=body.auth_method,
            auth_header=body.auth_header,
            auth_username=body.auth_username,
            extra_headers=body.extra_headers,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )

    status = await AiClient(config).status()
    # A provider's error text can echo back a URL that carries a credential.
    return AiStatusOut(
        ok=status.ok,
        detail=store.redact(db, status.detail),
        models=status.models[:50],
    )
