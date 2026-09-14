"""Authentication: password login, signed session cookies, and API tokens.

Design notes:

* Passwords and API tokens are hashed with Argon2id. Tokens are shown once, at
  creation, and only their hash is kept.
* Session cookies are stateless and HMAC-signed with the instance key, so there is
  no session table to prune. Revocation still works because the signature covers a
  fingerprint of the user's password hash: changing a password, or disabling an
  account, invalidates every outstanding cookie for it.
* On an empty database MARS creates one admin and prints a generated password to
  the log. No default credentials ship with the product.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets as pysecrets
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy.orm import Session

from .models import ApiToken, Role, User, utcnow
from .secrets import load_or_create_key
from .settings import settings

log = logging.getLogger(__name__)

_hasher = PasswordHasher()

TOKEN_PREFIX = "mars_pat_"
_COOKIE_SEP = "."


class AuthError(RuntimeError):
    pass


@dataclass
class Principal:
    """Who is making a request, and how they proved it."""

    user: User
    via: str  # "session" | "token"

    @property
    def username(self) -> str:
        return self.user.username

    @property
    def role(self) -> str:
        return self.user.role

    def can_write(self) -> bool:
        return self.role in (Role.ADMIN.value, Role.EDITOR.value)

    def is_admin(self) -> bool:
        return self.role == Role.ADMIN.value


# -- passwords --------------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# -- session cookies --------------------------------------------------------


def _signing_key() -> bytes:
    # Derived from the instance key rather than reusing it, so a cookie signature
    # can never be confused with secret-store ciphertext.
    return hashlib.sha256(b"mars-session-v1" + load_or_create_key()).digest()


def _password_fingerprint(user: User) -> str:
    digest = hashlib.sha256(user.password_hash.encode()).digest()[:8]
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def create_session_token(user: User, ttl_hours: int | None = None) -> str:
    ttl = ttl_hours if ttl_hours is not None else settings().session_ttl_hours
    expires = int(time.time()) + ttl * 3600
    payload = f"{user.id}{_COOKIE_SEP}{expires}{_COOKIE_SEP}{_password_fingerprint(user)}"
    sig = hmac.new(_signing_key(), payload.encode(), hashlib.sha256).digest()
    return payload + _COOKIE_SEP + base64.urlsafe_b64encode(sig).decode().rstrip("=")


def verify_session_token(token: str, db: Session) -> User | None:
    try:
        uid_s, exp_s, fingerprint, sig_s = token.split(_COOKIE_SEP)
    except ValueError:
        return None

    payload = f"{uid_s}{_COOKIE_SEP}{exp_s}{_COOKIE_SEP}{fingerprint}"
    expected = hmac.new(_signing_key(), payload.encode(), hashlib.sha256).digest()
    try:
        given = base64.urlsafe_b64decode(sig_s + "=" * (-len(sig_s) % 4))
    except Exception:
        return None
    if not hmac.compare_digest(expected, given):
        return None

    try:
        if int(exp_s) < time.time():
            return None
        user = db.get(User, int(uid_s))
    except (ValueError, TypeError):
        return None

    if user is None or user.disabled:
        return None
    # A password change rotates the fingerprint, which logs out every session.
    if not hmac.compare_digest(_password_fingerprint(user), fingerprint):
        return None
    return user


# -- API tokens -------------------------------------------------------------


def issue_api_token(
    db: Session, user: User, name: str, expires_at=None
) -> tuple[ApiToken, str]:
    """Creates a token. The plaintext is returned once and never stored."""
    raw = pysecrets.token_urlsafe(32)
    plaintext = TOKEN_PREFIX + raw
    prefix = plaintext[: len(TOKEN_PREFIX) + 6]

    token = ApiToken(
        user_id=user.id,
        name=name,
        prefix=prefix,
        token_hash=_hasher.hash(plaintext),
        expires_at=expires_at,
    )
    db.add(token)
    return token, plaintext


def verify_api_token(db: Session, plaintext: str) -> User | None:
    if not plaintext.startswith(TOKEN_PREFIX):
        return None
    prefix = plaintext[: len(TOKEN_PREFIX) + 6]

    # The prefix narrows the search; the hash comparison is what authenticates.
    candidates = db.query(ApiToken).filter(ApiToken.prefix == prefix).all()
    now = utcnow()
    for token in candidates:
        if token.expires_at is not None and token.expires_at < now:
            continue
        try:
            _hasher.verify(token.token_hash, plaintext)
        except (VerifyMismatchError, InvalidHashError):
            continue
        user = db.get(User, token.user_id)
        if user is None or user.disabled:
            return None
        token.last_used_at = now
        return user
    return None


# -- bootstrap --------------------------------------------------------------


def ensure_admin_user(db: Session) -> tuple[User, str | None] | None:
    """Creates the first admin if the user table is empty.

    Returns the user and its generated password on creation, or None if users
    already exist. The password is printed once to the log; there is no default.
    """
    if db.query(User).count() > 0:
        return None

    password = pysecrets.token_urlsafe(18)
    user = User(
        username="admin",
        password_hash=hash_password(password),
        role=Role.ADMIN.value,
        must_change_password=True,
    )
    db.add(user)
    db.flush()

    log.warning(
        "\n"
        "  ============================================================\n"
        "   MARS created its first administrator.\n"
        "     username: admin\n"
        "     password: %s\n"
        "   Change it after signing in; this is shown only once.\n"
        "  ============================================================",
        password,
    )
    return user, password
