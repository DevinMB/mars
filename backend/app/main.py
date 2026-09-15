"""MARS console - stream pipelines for Apache Flink(R)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from starlette.responses import Response

from .auth import ensure_admin_user
from .db import Base, engine, session_scope
from .migrations import upgrade_to_head
from .deps import get_cluster, get_registry, get_submitter, get_targets
from .ddl import DdlError
from .routes import ai as ai_routes
from .routes import auth as auth_routes
from .routes import catalog as catalog_routes
from .routes import jobs as job_routes
from .routes import portability as portability_routes
from .routes import secrets as secret_routes
from .routes import system as system_routes
from .routes import targets as target_routes
from .routes import users as user_routes
from .scheduler import Scheduler
from .secrets import SecretError
from .settings import settings
from .submitter import SubmissionError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("mars")

JOBS_RUNNING = Gauge("mars_jobs_running", "Jobs MARS believes are running")
JOBS_FAILED = Gauge("mars_jobs_failed", "Jobs whose most recent run failed")
SUBMISSIONS = Counter("mars_job_submissions_total", "Job submissions", ["outcome"])

_scheduler: Scheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler

    settings().data_dir.mkdir(parents=True, exist_ok=True)
    # Alembic owns the schema. create_all would add missing tables but never
    # missing columns, so an upgrade that adds one would start and then fail at the
    # first query mentioning it.
    upgrade_to_head()

    with session_scope() as db:
        ensure_admin_user(db)
        # Every job without an explicit target runs here, so it must exist before
        # anything is submitted.
        get_targets().ensure_default(db)

    registry = get_registry()
    log.info(
        "Loaded %d connector(s): %s",
        len(registry.all()),
        ", ".join(c.connector for c in registry.all()) or "none",
    )

    if await get_cluster().reachable():
        log.info("Flink is reachable at %s", settings().flink_rest_url)
    else:
        # Not fatal: the console should come up and say the cluster is down
        # rather than refuse to start.
        log.warning(
            "Flink is not reachable at %s. The console will start, but jobs "
            "cannot run until it is.",
            settings().flink_rest_url,
        )

    _scheduler = Scheduler(get_submitter(), get_targets())
    _scheduler.start()
    try:
        yield
    finally:
        if _scheduler is not None:
            await _scheduler.stop()


app = FastAPI(
    title="MARS",
    description="Stream pipelines for Apache Flink",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(auth_routes.router)
app.include_router(system_routes.router)
app.include_router(secret_routes.router)
app.include_router(catalog_routes.router)
app.include_router(job_routes.router)
app.include_router(target_routes.router)
app.include_router(user_routes.router)
app.include_router(ai_routes.router)
app.include_router(portability_routes.router)


@app.exception_handler(SubmissionError)
async def _submission_error(_: Request, exc: SubmissionError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": exc.summary})


@app.exception_handler(DdlError)
async def _ddl_error(_: Request, exc: DdlError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(SecretError)
async def _secret_error(_: Request, exc: SecretError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
async def readyz() -> Response:
    ok = await get_cluster().reachable()
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"flink": "up" if ok else "down"},
    )


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    from .models import Job, RunState

    with session_scope() as db:
        jobs = db.query(Job).all()
        running = failed = 0
        for job in jobs:
            latest = job.runs[0] if job.runs else None
            if latest is None:
                continue
            if latest.state == RunState.RUNNING.value:
                running += 1
            elif latest.state == RunState.FAILED.value:
                failed += 1
    JOBS_RUNNING.set(running)
    JOBS_FAILED.set(failed)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# The built frontend, when present. Mounted last so it cannot shadow the API.
_FRONTEND = Path(__file__).resolve().parent.parent / "static"
if _FRONTEND.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> Response:
        # Anything not matched by the API falls through to the single-page app,
        # so a deep link like /jobs/my-job survives a refresh.
        candidate = _FRONTEND / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND / "index.html")
