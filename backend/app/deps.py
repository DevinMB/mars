"""Shared FastAPI dependencies: authentication, authorisation, and the singletons
that talk to Flink."""
from __future__ import annotations

from functools import lru_cache

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .auth import Principal, verify_api_token, verify_session_token
from .cluster import FlinkClusterClient
from .db import get_session
from .gateway import SqlGatewayClient
from .registry import ConnectorRegistry
from .secrets import SecretStore
from .settings import settings
from .submitter import JobSubmitter


@lru_cache
def get_registry() -> ConnectorRegistry:
    s = settings()
    reg = ConnectorRegistry(bundled_dir=_bundled_dir(), jar_dir=s.connector_lib_dir)
    reg.load()
    return reg


def _bundled_dir():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent / "manifests"


@lru_cache
def get_secret_store() -> SecretStore:
    return SecretStore()


@lru_cache
def get_gateway() -> SqlGatewayClient:
    s = settings()
    return SqlGatewayClient(s.sql_gateway_url, timeout=s.request_timeout_seconds)


@lru_cache
def get_cluster() -> FlinkClusterClient:
    return FlinkClusterClient(settings().flink_rest_url)


@lru_cache
def get_submitter() -> JobSubmitter:
    return JobSubmitter(get_gateway(), get_cluster(), get_secret_store())


def current_principal(
    db: Session = Depends(get_session),
    mars_session: str | None = Cookie(default=None, alias="mars_session"),
    authorization: str | None = Header(default=None),
) -> Principal:
    """Resolves the caller from a session cookie or a bearer token."""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        user = verify_api_token(db, token)
        if user is not None:
            db.commit()  # persist last_used_at
            return Principal(user=user, via="token")

    if mars_session:
        user = verify_session_token(mars_session, db)
        if user is not None:
            return Principal(user=user, via="session")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not signed in",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_writer(principal: Principal = Depends(current_principal)) -> Principal:
    if not principal.can_write():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has read-only access.",
        )
    return principal


def require_admin(principal: Principal = Depends(current_principal)) -> Principal:
    if not principal.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires an administrator.",
        )
    return principal
