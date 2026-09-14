"""The admin CLI is the recovery path when nobody can sign in, so it has to work
against a database the application has never touched."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import admin, auth
from app.models import Role, User


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """Point the CLI's session_scope at a throwaway SQLite file."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from contextlib import contextmanager

    from app import settings as settings_mod
    settings_mod.settings.cache_clear()
    monkeypatch.setenv("MARS_DATA_DIR", str(tmp_path))

    engine = create_engine(f"sqlite:///{tmp_path}/admin.db")
    from app.db import Base
    import app.models  # noqa: F401
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def scope():
        s = Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(admin, "session_scope", scope)
    monkeypatch.setattr(admin.Base.metadata, "create_all", lambda *a, **k: None)
    yield Session
    settings_mod.settings.cache_clear()


def _users(Session):
    with Session() as s:
        return s.scalars(select(User)).all()


def test_create_user_generates_a_password(capsys, _isolated):
    assert admin.main(["create-user", "devin", "--role", "admin"]) == 0
    out = capsys.readouterr().out
    assert "username: devin" in out

    password = next(l.split("password:")[1].strip() for l in out.splitlines() if "password:" in l)
    users = _users(_isolated)
    assert len(users) == 1
    assert auth.verify_password(users[0].password_hash, password)
    assert users[0].role == Role.ADMIN.value
    # A generated password should prompt the operator to replace it.
    assert users[0].must_change_password


def test_create_user_with_explicit_password_does_not_nag(_isolated):
    admin.main(["create-user", "devin", "--password", "a-chosen-password"])
    user = _users(_isolated)[0]
    assert auth.verify_password(user.password_hash, "a-chosen-password")
    assert not user.must_change_password


def test_duplicate_user_is_refused(_isolated, capsys):
    admin.main(["create-user", "devin"])
    assert admin.main(["create-user", "devin"]) == 1


def test_reset_password_recovers_a_locked_out_install(capsys, _isolated):
    admin.main(["create-user", "admin", "--role", "admin", "--password", "forgotten"])
    capsys.readouterr()

    assert admin.main(["reset-password", "admin"]) == 0
    out = capsys.readouterr().out
    password = next(l.split("password:")[1].strip() for l in out.splitlines() if "password:" in l)

    user = _users(_isolated)[0]
    assert auth.verify_password(user.password_hash, password)
    assert not auth.verify_password(user.password_hash, "forgotten")
    # A reset must end any session that was open with the old credentials.
    assert "sessions are now invalid" in out


def test_reset_password_reenables_a_disabled_account(_isolated):
    admin.main(["create-user", "admin", "--role", "admin", "--password", "x"])
    admin.main(["disable-user", "admin"])
    admin.main(["reset-password", "admin", "--password", "y"])
    assert not _users(_isolated)[0].disabled


def test_reset_unknown_user_fails(_isolated):
    assert admin.main(["reset-password", "nobody"]) == 1


def test_cannot_disable_the_only_admin(_isolated, capsys):
    admin.main(["create-user", "admin", "--role", "admin", "--password", "x"])
    assert admin.main(["disable-user", "admin"]) == 1
    assert "only administrator" in capsys.readouterr().err
    assert not _users(_isolated)[0].disabled


def test_can_disable_an_admin_when_another_remains(_isolated):
    admin.main(["create-user", "a", "--role", "admin", "--password", "x"])
    admin.main(["create-user", "b", "--role", "admin", "--password", "x"])
    assert admin.main(["disable-user", "a"]) == 0


def test_issue_and_revoke_token(capsys, _isolated):
    admin.main(["create-user", "ci", "--password", "x"])
    capsys.readouterr()

    assert admin.main(["issue-token", "ci", "--name", "deploy"]) == 0
    out = capsys.readouterr().out
    token = next(l.strip() for l in out.splitlines() if l.strip().startswith(auth.TOKEN_PREFIX))

    with _isolated() as s:
        assert auth.verify_api_token(s, token) is not None

    assert admin.main(["revoke-token", "--name", "deploy"]) == 0
    with _isolated() as s:
        assert auth.verify_api_token(s, token) is None


def test_list_users_on_empty_database_explains_what_to_do(capsys, _isolated):
    assert admin.main(["list-users"]) == 0
    assert "create-user" in capsys.readouterr().out
