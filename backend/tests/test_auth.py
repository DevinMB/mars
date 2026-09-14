"""Auth tests focus on the properties that matter: tokens are not recoverable
from storage, sessions cannot be forged, and revocation actually revokes."""
from __future__ import annotations

import time

import pytest

from app import auth
from app.models import Role, User


@pytest.fixture
def user(db) -> User:
    u = User(username="devin", password_hash=auth.hash_password("correct horse"),
             role=Role.ADMIN.value)
    db.add(u)
    db.commit()
    return u


@pytest.fixture(autouse=True)
def _key(monkeypatch, tmp_path):
    from app import settings as settings_mod
    settings_mod.settings.cache_clear()
    monkeypatch.setenv("MARS_DATA_DIR", str(tmp_path))
    yield
    settings_mod.settings.cache_clear()


def test_password_hash_is_not_the_password(user):
    assert "correct horse" not in user.password_hash
    assert user.password_hash.startswith("$argon2")


def test_password_verification(user):
    assert auth.verify_password(user.password_hash, "correct horse")
    assert not auth.verify_password(user.password_hash, "wrong")


def test_verify_password_survives_garbage_hash():
    # A corrupted row must fail closed, not raise into a 500.
    assert not auth.verify_password("not-a-hash", "anything")


def test_session_round_trip(db, user):
    token = auth.create_session_token(user)
    assert auth.verify_session_token(token, db) is not None
    assert auth.verify_session_token(token, db).id == user.id


def test_tampered_session_is_rejected(db, user):
    token = auth.create_session_token(user)
    uid, exp, fp, sig = token.split(".")

    # Claim to be a different user id, keeping the original signature.
    forged = f"{int(uid) + 1}.{exp}.{fp}.{sig}"
    assert auth.verify_session_token(forged, db) is None

    # Extend the expiry.
    forged = f"{uid}.{int(exp) + 99999}.{fp}.{sig}"
    assert auth.verify_session_token(forged, db) is None


def test_expired_session_is_rejected(db, user):
    token = auth.create_session_token(user, ttl_hours=0)
    time.sleep(1.1)
    assert auth.verify_session_token(token, db) is None


def test_malformed_session_is_rejected(db):
    for bad in ["", "a", "a.b", "a.b.c", "....", "1.2.3.notbase64!!"]:
        assert auth.verify_session_token(bad, db) is None


def test_password_change_invalidates_existing_sessions(db, user):
    token = auth.create_session_token(user)
    assert auth.verify_session_token(token, db) is not None

    user.password_hash = auth.hash_password("a new password")
    db.commit()

    assert auth.verify_session_token(token, db) is None


def test_disabling_a_user_invalidates_sessions(db, user):
    token = auth.create_session_token(user)
    user.disabled = True
    db.commit()
    assert auth.verify_session_token(token, db) is None


def test_api_token_is_stored_only_as_a_hash(db, user):
    token, plaintext = auth.issue_api_token(db, user, "ci")
    db.commit()

    assert plaintext.startswith(auth.TOKEN_PREFIX)
    assert plaintext not in token.token_hash
    assert token.token_hash.startswith("$argon2")
    # The prefix is safe to display and is not enough to authenticate.
    assert token.prefix in plaintext
    assert auth.verify_api_token(db, token.prefix) is None


def test_api_token_round_trip(db, user):
    _, plaintext = auth.issue_api_token(db, user, "ci")
    db.commit()

    found = auth.verify_api_token(db, plaintext)
    assert found is not None and found.id == user.id


def test_api_token_records_last_used(db, user):
    _, plaintext = auth.issue_api_token(db, user, "ci")
    db.commit()
    assert auth.verify_api_token(db, plaintext).id == user.id
    db.commit()

    from app.models import ApiToken
    assert db.query(ApiToken).one().last_used_at is not None


def test_expired_api_token_is_rejected(db, user):
    from datetime import timedelta
    from app.models import utcnow

    _, plaintext = auth.issue_api_token(db, user, "old", expires_at=utcnow() - timedelta(seconds=1))
    db.commit()
    assert auth.verify_api_token(db, plaintext) is None


def test_unknown_token_is_rejected(db, user):
    auth.issue_api_token(db, user, "ci")
    db.commit()
    assert auth.verify_api_token(db, auth.TOKEN_PREFIX + "totallymadeup") is None
    assert auth.verify_api_token(db, "not-even-a-mars-token") is None


def test_bootstrap_creates_one_admin_with_a_generated_password(db):
    result = auth.ensure_admin_user(db)
    assert result is not None
    user, password = result
    db.commit()

    assert user.username == "admin"
    assert user.role == Role.ADMIN.value
    assert user.must_change_password
    assert len(password) >= 20
    assert auth.verify_password(user.password_hash, password)

    # Running again must not create a second admin or rotate the password.
    assert auth.ensure_admin_user(db) is None


def test_roles_gate_writes(db):
    for role, writable in [(Role.ADMIN, True), (Role.EDITOR, True), (Role.VIEWER, False)]:
        u = User(username=f"u{role.value}", password_hash="x", role=role.value)
        p = auth.Principal(user=u, via="session")
        assert p.can_write() is writable
        assert p.is_admin() is (role is Role.ADMIN)
