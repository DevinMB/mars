from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import hash_password, issue_api_token
from app.db import get_session
from app.deps import require_admin, require_writer
from app.models import User
from app.routes import auth
from app.security import LoginLimiter, install_browser_security
from app.settings import settings

HEADERS = {"X-MARS-Request": "1"}


@pytest.fixture
def client(db, tmp_path, monkeypatch):
    monkeypatch.setenv("MARS_DATA_DIR", str(tmp_path))
    settings.cache_clear()
    monkeypatch.setattr(auth, "login_limiter", LoginLimiter())
    db.add(User(username="operator", role="admin", password_hash=hash_password("synthetic-password")))
    db.commit()
    app = FastAPI()
    install_browser_security(app)
    app.include_router(auth.router)
    app.dependency_overrides[get_session] = lambda: db

    @app.post("/api/write")
    def write(user=Depends(require_writer)):
        return {"user": user.username}

    @app.get("/api/admin")
    def admin(user=Depends(require_admin)):
        return {"user": user.username}

    with TestClient(app) as client:
        yield client
    settings.cache_clear()


def sign_in(client):
    response = client.post("/api/auth/login", headers=HEADERS,
                           json={"username": "operator", "password": "synthetic-password"})
    assert response.status_code == 200


def test_cookie_writes_require_header_even_from_same_site(client):
    sign_in(client)
    assert client.post("/api/write", headers={"Origin": "http://testserver:9999", "Sec-Fetch-Site": "same-site"}).status_code == 403
    assert client.post("/api/write", headers=HEADERS).status_code == 200
    preflight = client.options("/api/write", headers={
        "Origin": "http://untrusted.example", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-mars-request",
    })
    assert "access-control-allow-origin" not in preflight.headers


def test_login_and_logout_require_header(client):
    assert client.post("/api/auth/login", json={"username": "operator", "password": "synthetic-password"}).status_code == 403
    sign_in(client)
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers=HEADERS).status_code == 204


def test_invalid_bearer_never_falls_back_to_valid_cookie(client):
    sign_in(client)
    assert client.post("/api/write", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Basic invalid"}).status_code == 401


@pytest.mark.parametrize("role,write_status,admin_status", [("viewer", 403, 403), ("editor", 200, 403), ("admin", 200, 200)])
def test_bearer_automation_and_server_side_roles(client, db, role, write_status, admin_status):
    user = db.query(User).one()
    user.role = role
    _, token = issue_api_token(db, user, "synthetic-automation")
    db.commit()
    headers = {"Authorization": "Bearer " + token}
    assert client.post("/api/write", headers=headers).status_code == write_status
    assert client.get("/api/admin", headers=headers).status_code == admin_status
    user.disabled = True
    db.commit()
    assert client.post("/api/write", headers=headers).status_code == 401


def test_login_rate_limit_runs_before_password_verification(client, monkeypatch):
    monkeypatch.setattr(auth, "login_limiter", LoginLimiter(per_client=2))
    calls = []
    monkeypatch.setattr(auth, "verify_password", lambda *args: calls.append(1) or False)
    for _ in range(2):
        assert client.post("/api/auth/login", headers=HEADERS, json={"username": "unknown", "password": "wrong"}).status_code == 401
    response = client.post("/api/auth/login", headers=HEADERS, json={"username": "operator", "password": "synthetic-password"})
    assert response.status_code == 429
    assert 1 <= int(response.headers["Retry-After"]) <= 60
    assert len(calls) == 2


def test_sensitive_responses_are_not_cached_or_framed(client):
    for response in [client.get("/api/auth/me"), client.post("/api/auth/login")]:
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_limiter_is_bounded_thread_safe_and_recovers():
    now = [0.0]
    limiter = LoginLimiter(per_client=3, global_limit=5, clock=lambda: now[0])
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(limiter.retry_after, ["same-client"] * 30))
    assert outcomes.count(0) == 3
    assert limiter.retry_after("second") == 0
    assert limiter.retry_after("third") == 0
    assert limiter.retry_after("rotated-address") == 60
    assert len(limiter.attempts) == 5
    now[0] = 60.0
    assert limiter.retry_after("same-client") == 0
    assert len(limiter.attempts) == 1
