"""User administration.

The interesting tests are the ones that stop an installation being locked out of
itself. Everything else is CRUD."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import auth
from app.auth import Principal
from app.models import ApiToken, Role, User
from app.routes import users as mod
from app.schemas import TokenIn, UserIn, UserUpdate


def _user(db, name, role=Role.EDITOR, disabled=False):
    u = User(username=name, password_hash=auth.hash_password("x" * 14),
             role=role.value, disabled=disabled)
    db.add(u)
    db.commit()
    return u


def _principal(u):
    return Principal(user=u, via="session")


@pytest.fixture
def admin(db):
    return _user(db, "admin", Role.ADMIN)


# -- lockout protection ----------------------------------------------------


def test_the_only_admin_cannot_be_demoted(db, admin):
    with pytest.raises(HTTPException) as exc:
        mod.update_user("admin", UserUpdate(role="viewer"), _principal(admin), db)
    assert exc.value.status_code == 409
    assert "only administrator" in exc.value.detail
    assert db.scalar(select(User).where(User.username == "admin")).role == Role.ADMIN.value


def test_the_only_admin_cannot_be_disabled(db, admin):
    other = _user(db, "someone_else", Role.ADMIN)
    # Another admin exists but is disabled, so it does not count.
    other.disabled = True
    db.commit()
    with pytest.raises(HTTPException, match="only administrator"):
        mod.update_user("admin", UserUpdate(disabled=True), _principal(other), db)


def test_the_only_admin_cannot_be_deleted(db, admin):
    second = _user(db, "second", Role.ADMIN)
    with pytest.raises(HTTPException, match="only administrator"):
        # Deleting the second admin is fine; deleting the first while it is alone
        # is not. Demote the second to make the first the only one.
        mod.update_user("second", UserUpdate(role="viewer"), _principal(admin), db)
        mod.delete_user("admin", _principal(second), db)


def test_an_admin_can_be_demoted_when_another_remains(db, admin):
    _user(db, "second", Role.ADMIN)
    out = mod.update_user("admin", UserUpdate(role="editor"), _principal(admin), db)
    assert out.role == "editor"


def test_you_cannot_disable_yourself(db, admin):
    _user(db, "second", Role.ADMIN)
    with pytest.raises(HTTPException, match="your own account"):
        mod.update_user("admin", UserUpdate(disabled=True), _principal(admin), db)


def test_you_cannot_delete_yourself(db, admin):
    _user(db, "second", Role.ADMIN)
    with pytest.raises(HTTPException, match="your own account"):
        mod.delete_user("admin", _principal(admin), db)


# -- creation --------------------------------------------------------------


def test_create_generates_a_password_and_returns_it_once(db, admin):
    out = mod.create_user(UserIn(username="operator", role="editor"), _principal(admin), db)
    assert out.password and len(out.password) >= 20
    user = db.scalar(select(User).where(User.username == "operator"))
    assert auth.verify_password(user.password_hash, out.password)
    # A generated password should be replaced by its owner.
    assert user.must_change_password


def test_create_with_a_chosen_password_returns_nothing_and_does_not_nag(db, admin):
    out = mod.create_user(
        UserIn(username="operator", role="viewer", password="a-chosen-password"),
        _principal(admin), db)
    assert out.password is None
    assert not db.scalar(select(User).where(User.username == "operator")).must_change_password


def test_duplicate_username_is_refused(db, admin):
    mod.create_user(UserIn(username="operator"), _principal(admin), db)
    with pytest.raises(HTTPException) as exc:
        mod.create_user(UserIn(username="operator"), _principal(admin), db)
    assert exc.value.status_code == 409


@pytest.mark.parametrize("bad", ["has space", "has/slash", "", "-leading"])
def test_invalid_usernames_are_refused(bad):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        UserIn(username=bad)


def test_role_must_be_one_of_the_three():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        UserIn(username="x", role="superuser")


# -- password reset --------------------------------------------------------


def test_reset_invalidates_sessions_and_reenables(db, admin):
    target = _user(db, "locked", Role.EDITOR, disabled=True)
    before = target.password_hash
    token = auth.create_session_token(target)

    out = mod.reset_password("locked", _principal(admin), db)

    assert out.password
    db.refresh(target)
    assert target.password_hash != before
    assert not target.disabled
    # The session signature covers a fingerprint of the hash, so a reset ends
    # every open session for that user.
    assert auth.verify_session_token(token, db) is None


# -- tokens ----------------------------------------------------------------


def test_token_is_returned_once_and_stored_hashed(db, admin):
    out = mod.create_token("admin", TokenIn(name="ci"), _principal(admin), db)
    assert out.token and out.token.startswith(auth.TOKEN_PREFIX)

    stored = db.query(ApiToken).one()
    assert out.token not in stored.token_hash
    assert auth.verify_api_token(db, out.token).username == "admin"

    # Listing never includes the value again.
    listed = mod.list_tokens("admin", _principal(admin), db)
    assert listed[0].token is None
    assert listed[0].prefix == stored.prefix


def test_revoking_a_token_stops_it_working(db, admin):
    out = mod.create_token("admin", TokenIn(name="ci"), _principal(admin), db)
    mod.revoke_token("admin", "ci", _principal(admin), db)
    assert auth.verify_api_token(db, out.token) is None


def test_expiring_token_records_its_expiry(db, admin):
    out = mod.create_token("admin", TokenIn(name="ci", expires_days=30), _principal(admin), db)
    assert out.expires_at is not None


def test_secret_listing_is_available_to_writers_but_management_is_not():
    """An editor creating a sink must be able to pick which credential it uses, so
    the connector form can fill its dropdown. Values are never returned by any
    endpoint; what a writer learns is which names exist."""
    from app.deps import require_admin, require_writer
    from app.routes import secrets as mod

    guards = {}
    for route in mod.router.routes:
        method = sorted(route.methods - {"HEAD", "OPTIONS"})[0]
        guards[(method, route.path)] = [d.call for d in route.dependant.dependencies]

    assert require_writer in guards[("GET", "/api/secrets")]
    assert require_admin not in guards[("GET", "/api/secrets")]

    for key in [("PUT", "/api/secrets/{name}"), ("DELETE", "/api/secrets/{name}")]:
        assert require_admin in guards[key], f"{key} must require an administrator"
