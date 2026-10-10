"""Browser request protection and bounded, per-process login throttling."""
from collections import deque
from math import ceil
from threading import Lock
from time import monotonic

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from .settings import settings


class LoginLimiter:
    """Reserve attempts before hashing; IP rotation cannot bypass the global cap.

    Only accepted attempts are retained, so memory is bounded by global_limit.
    Use a shared limiter at the proxy if running more than one console process.
    """

    def __init__(self, per_client=10, global_limit=100, window=60, clock=monotonic):
        self.per_client = per_client
        self.global_limit = global_limit
        self.window = window
        self.clock = clock
        self.attempts = deque()
        self.lock = Lock()

    def retry_after(self, client: str) -> int:
        with self.lock:
            now = self.clock()
            while self.attempts and self.attempts[0][0] <= now - self.window:
                self.attempts.popleft()
            own = [stamp for stamp, peer in self.attempts if peer == client]
            deadlines = []
            if len(own) >= self.per_client:
                deadlines.append(own[0] + self.window)
            if len(self.attempts) >= self.global_limit:
                deadlines.append(self.attempts[0][0] + self.window)
            if deadlines:
                return max(1, ceil(max(deadlines) - now))
            self.attempts.append((now, client))
            return 0


login_limiter = LoginLimiter()


def install_browser_security(app: FastAPI) -> None:
    @app.middleware("http")
    async def browser_security(request: Request, call_next):
        path = request.scope["path"]
        is_api = path == "/api" or path.startswith("/api/")
        unsafe = request.method not in {"GET", "HEAD", "OPTIONS"}
        auth_action = path.rstrip("/") in {"/api/auth/login", "/api/auth/logout"}
        bearer = request.headers.get("authorization", "").lower().startswith("bearer ")
        cookie_auth = settings().session_cookie in request.cookies and not bearer
        # A custom header forces cross-origin browsers to preflight. The API
        # intentionally grants no CORS access. Never fall back from invalid
        # bearer auth to cookies, or this exemption would bypass the protection.
        if is_api and unsafe and (auth_action or cookie_auth) and request.headers.get("x-mars-request") != "1":
            response = JSONResponse(status_code=403, content={
                "detail": "Browser write requests require X-MARS-Request: 1. Refresh the page and try again."
            })
        else:
            response = await call_next(request)
        if is_api:
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        return response
