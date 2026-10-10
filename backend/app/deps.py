"""Shared FastAPI dependencies: authentication, authorisation, and the singletons
that talk to Flink."""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from .auth import Principal, verify_api_token, verify_session_token
from .cluster import FlinkClusterClient
from .db import get_session
from .gateway import SqlGatewayClient
from .registry import ConnectorRegistry
from .secrets import SecretStore
from .settings import settings
from .submitter import JobSubmitter
from .targets import TargetRegistry


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
def get_targets() -> TargetRegistry:
    """Resolves a job's execution target to the clients that talk to that cluster."""
    return TargetRegistry(get_secret_store())


@lru_cache
def get_submitter() -> JobSubmitter:
    """The default target's submitter.

    Still used where no job is in hand -- the scheduler's reconcile pass and the
    startup reachability check. Anything acting on a specific job resolves that
    job's target instead.
    """
    return JobSubmitter(get_gateway(), get_cluster(), get_secret_store())


def current_principal(
    request: Request,
    db: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> Principal:
    """Resolves the caller from a session cookie or a bearer token."""
    if authorization is not None:
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        user = verify_api_token(db, token)
        if user is not None:
            db.commit()  # persist last_used_at
            return Principal(user=user, via="token")
        raise HTTPException(status_code=401, detail="Invalid API token",
                            headers={"WWW-Authenticate": "Bearer"})

    mars_session = request.cookies.get(settings().session_cookie)
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
