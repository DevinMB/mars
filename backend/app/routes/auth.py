"""Sign-in, sign-out, and account self-service."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..auth import (
    Principal,
    create_session_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from ..db import get_session
from ..deps import current_principal
from ..models import User, utcnow
from ..schemas import ChangePasswordRequest, LoginRequest, MeResponse
from ..settings import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=MeResponse)
def login(
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_session),
) -> MeResponse:
    user = db.query(User).filter(User.username == body.username).one_or_none()

    # Same response whether the user is unknown, disabled, or the password is
    # wrong, so this endpoint cannot be used to enumerate accounts.
    if user is None or user.disabled or not verify_password(user.password_hash, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
        )

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    user.last_login_at = utcnow()
    db.commit()

    s = settings()
    response.set_cookie(
        key=s.session_cookie,
        value=create_session_token(user),
        httponly=True,
        samesite="lax",
        max_age=s.session_ttl_hours * 3600,
        path="/",
    )
    return MeResponse(
        username=user.username,
        role=user.role,
        must_change_password=user.must_change_password,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def logout(response: Response) -> None:
    response.delete_cookie(settings().session_cookie, path="/")


@router.get("/me", response_model=MeResponse)
def me(principal: Principal = Depends(current_principal)) -> MeResponse:
    return MeResponse(
        username=principal.username,
        role=principal.role,
        must_change_password=principal.user.must_change_password,
    )


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def change_password(
    body: ChangePasswordRequest,
    response: Response,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
) -> None:
    user = principal.user
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )
    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The new password must be different.",
        )

    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()

    # Changing the password invalidates every existing cookie, this one included,
    # so issue a fresh one rather than silently signing the user out.
    s = settings()
    response.set_cookie(
        key=s.session_cookie,
        value=create_session_token(user),
        httponly=True,
        samesite="lax",
        max_age=s.session_ttl_hours * 3600,
        path="/",
    )
