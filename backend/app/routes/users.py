"""User and API token administration.

The CLI can already do all of this and remains the recovery path when nobody can
sign in. This is the same ground for the common case, where an administrator is
already signed in and wants to add a colleague.

The rules that keep an installation usable live here rather than in the page,
because a UI guard is a convenience and an API guard is the actual boundary:

* The last enabled administrator cannot be demoted, disabled or deleted. Without
  this, one careless edit locks everyone out of the console and the only way back
  is a shell on the host.
* You cannot delete or disable yourself. It is almost never meant, and it is
  irritating to undo.
"""
from __future__ import annotations

import secrets as pysecrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import (
    Principal,
    hash_password,
    issue_api_token,
)
from ..db import get_session
from ..deps import require_admin
from ..models import ApiToken, Role, User, utcnow
from ..schemas import (
    PasswordResetOut,
    TokenIn,
    TokenOut,
    UserIn,
    UserOut,
    UserUpdate,
)

router = APIRouter(prefix="/api/users", tags=["users"])


def _out(db: Session, user: User, me: Principal) -> UserOut:
    return UserOut(
        username=user.username,
        role=user.role,
        disabled=user.disabled,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        token_count=db.query(ApiToken).filter(ApiToken.user_id == user.id).count(),
        is_self=user.id == me.user.id,
    )


def _get(db: Session, username: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(status_code=404, detail=f"No user named '{username}'")
    return user


def _other_admins(db: Session, user: User) -> int:
    """Enabled administrators other than this one."""
    return (
        db.query(User)
        .filter(User.role == Role.ADMIN.value, User.disabled.is_(False), User.id != user.id)
        .count()
    )


def _guard_last_admin(db: Session, user: User, action: str) -> None:
    if user.role != Role.ADMIN.value or user.disabled:
        return
    if _other_admins(db, user) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"'{user.username}' is the only administrator, so it cannot be {action}. "
                f"Promote another account first, or nobody will be able to manage this "
                f"installation."
            ),
        )


@router.get("", response_model=list[UserOut])
def list_users(
    me: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
) -> list[UserOut]:
    rows = list(db.scalars(select(User).order_by(User.username)))
    return [_out(db, u, me) for u in rows]


@router.post("", response_model=PasswordResetOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserIn,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
) -> PasswordResetOut:
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user named '{body.username}' already exists.",
        )

    generated = body.password is None
    password = body.password or pysecrets.token_urlsafe(18)
    db.add(
        User(
            username=body.username,
            password_hash=hash_password(password),
            role=body.role,
            # Only nag when MARS chose the password; one the admin set is theirs.
            must_change_password=generated,
        )
    )
    db.commit()
    return PasswordResetOut(username=body.username, password=password if generated else None)


@router.patch("/{username}", response_model=UserOut)
def update_user(
    username: str,
    body: UserUpdate,
    me: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
) -> UserOut:
    user = _get(db, username)

    if body.disabled is not None and body.disabled != user.disabled:
        if user.id == me.user.id and body.disabled:
            raise HTTPException(status_code=400, detail="You cannot disable your own account.")
        if body.disabled:
            _guard_last_admin(db, user, "disabled")
        user.disabled = body.disabled

    if body.role is not None and body.role != user.role:
        if user.role == Role.ADMIN.value and body.role != Role.ADMIN.value:
            _guard_last_admin(db, user, "demoted")
        user.role = body.role

    db.commit()
    return _out(db, user, me)


@router.post("/{username}/password", response_model=PasswordResetOut)
def reset_password(
    username: str,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
) -> PasswordResetOut:
    """Generates a new password and returns it once.

    Changing the hash invalidates every session cookie for this user, because the
    session signature covers a fingerprint of it. That is the behaviour you want
    from an administrative reset.
    """
    user = _get(db, username)
    password = pysecrets.token_urlsafe(18)
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.disabled = False
    db.commit()
    return PasswordResetOut(username=user.username, password=password)


@router.delete("/{username}", status_code=status.HTTP_204_NO_CONTENT,
               response_class=Response, response_model=None)
def delete_user(
    username: str,
    me: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
) -> None:
    user = _get(db, username)
    if user.id == me.user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")
    _guard_last_admin(db, user, "deleted")
    db.delete(user)
    db.commit()


# -- API tokens -------------------------------------------------------------


@router.get("/{username}/tokens", response_model=list[TokenOut])
def list_tokens(
    username: str,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
) -> list[TokenOut]:
    user = _get(db, username)
    rows = db.query(ApiToken).filter(ApiToken.user_id == user.id).order_by(ApiToken.name).all()
    return [
        TokenOut(
            name=t.name, prefix=t.prefix, created_at=t.created_at,
            expires_at=t.expires_at, last_used_at=t.last_used_at,
        )
        for t in rows
    ]


@router.post("/{username}/tokens", response_model=TokenOut,
             status_code=status.HTTP_201_CREATED)
def create_token(
    username: str,
    body: TokenIn,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
) -> TokenOut:
    user = _get(db, username)
    expires = utcnow() + timedelta(days=body.expires_days) if body.expires_days else None
    token, plaintext = issue_api_token(db, user, body.name, expires_at=expires)
    db.commit()
    return TokenOut(
        name=token.name, prefix=token.prefix, created_at=token.created_at,
        expires_at=token.expires_at, last_used_at=None,
        # The only time the value is ever returned.
        token=plaintext,
    )


@router.delete("/{username}/tokens/{name}", status_code=status.HTTP_204_NO_CONTENT,
               response_class=Response, response_model=None)
def revoke_token(
    username: str,
    name: str,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_session),
) -> None:
    user = _get(db, username)
    rows = db.query(ApiToken).filter(
        ApiToken.user_id == user.id, ApiToken.name == name
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No token named '{name}' for {username}")
    for t in rows:
        db.delete(t)
    db.commit()
