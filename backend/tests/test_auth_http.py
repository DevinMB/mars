"""Cookie policy must work across sign-in, password changes and sign-out."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import hash_password
from app.db import get_session
from app.models import User
from app.routes.auth import router
from app.settings import settings


@pytest.mark.parametrize("secure", [False, True])
def test_custom_cookie_and_secure_policy(db, tmp_path, monkeypatch, secure):
    monkeypatch.setenv("MARS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARS_SESSION_COOKIE", "custom_session")
    monkeypatch.setenv("MARS_SESSION_COOKIE_SECURE", str(secure).lower())
    settings.cache_clear()
    db.add(User(username="operator", password_hash=hash_password("synthetic-password"),
                role="admin", must_change_password=False))
    db.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: db
    try:
        client = TestClient(app, base_url="https://testserver" if secure else "http://testserver")
        response = client.post("/api/auth/login", json={"username": "operator", "password": "synthetic-password"})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "custom_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
        assert ("Secure" in cookie) == secure
        assert client.get("/api/auth/me").status_code == 200
        response = client.post("/api/auth/password", json={
            "current_password": "synthetic-password", "new_password": "replacement-password",
        })
        assert response.status_code == 204
        assert ("Secure" in response.headers["set-cookie"]) == secure
        assert client.get("/api/auth/me").status_code == 200
        assert client.post("/api/auth/logout").status_code == 204
        assert client.get("/api/auth/me").status_code == 401
    finally:
        settings.cache_clear()
