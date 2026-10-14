"""Job tags: one rule for every way in, and never a new job version."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import portability, tags
from app.auth import hash_password, issue_api_token
from app.db import get_session
from app.lineage import pipeline_graph
from app.models import Job, User
from app.routes import jobs as job_routes
from app.secrets import SecretStore


def test_tags_are_cleaned_and_validated():
    assert tags.clean([" Buoys", "ingest", "buoys", ""]) == ["buoys", "ingest"]
    for bad in (["has space"], ["-dash-first"], ["x" * 33], ["ok/no"]):
        with pytest.raises(ValueError):
            tags.clean(bad)
    with pytest.raises(ValueError, match="at most 10"):
        tags.clean([f"t{i}" for i in range(11)])


@pytest.fixture
def api(db):
    db.add(User(username="devin", role="editor", password_hash=hash_password("synthetic-password")))
    db.commit()
    _, token = issue_api_token(db, db.query(User).one(), "tests")
    db.commit()
    app = FastAPI()
    app.include_router(job_routes.router)
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app, headers={"Authorization": "Bearer " + token}) as client:
        yield client


def _job(client, name, **kw):
    body = {"name": name, "sql_text": "SELECT 1", **kw}
    r = client.post("/api/jobs", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_tags_are_set_from_the_editor_without_a_new_version(api):
    created = _job(api, "buoys_latest", tags=["Buoys", "ingest"])
    assert created["tags"] == ["buoys", "ingest"]
    r = api.put("/api/jobs/buoys_latest", json={"name": "buoys_latest", "sql_text": "SELECT 1", "tags": ["buoys"]})
    assert r.status_code == 200 and r.json()["tags"] == ["buoys"]
    assert r.json()["version"] == created["version"], "tags change nothing about how a job runs"
    bad = api.put("/api/jobs/buoys_latest", json={"name": "buoys_latest", "sql_text": "SELECT 1", "tags": ["no spaces"]})
    assert bad.status_code == 422


def test_bulk_tagging_adds_and_removes_across_jobs(api):
    _job(api, "a", tags=["old"])
    _job(api, "b")
    r = api.post("/api/jobs/tags", json={"jobs": ["a", "b"], "add": ["Buoys"], "remove": ["old"]})
    assert r.status_code == 200, r.text
    assert {j["name"]: j["tags"] for j in r.json()} == {"a": ["buoys"], "b": ["buoys"]}
    assert api.post("/api/jobs/tags", json={"jobs": ["nope"], "add": ["x"]}).status_code == 404


def test_tags_survive_export_and_import_and_reach_the_pipeline(db, monkeypatch):
    monkeypatch.setenv("MARS_SECRET_KEY", Fernet.generate_key().decode())
    store = SecretStore()
    job = Job(name="buoys_obs", sql_text="SELECT 1", catalog_refs="[]")
    tags.put(job, ["buoys"])
    db.add(job)
    db.commit()
    exported = portability.export_all(db, store)
    assert exported["jobs"][0]["tags"] == ["buoys"]

    exported["jobs"][0]["tags"] = ["buoys", "phase1"]
    version = job.version
    out = portability.import_all(db, store, exported, dry_run=False, replace=True)
    assert out.updated == ["job/buoys_obs"] and not out.errors
    db.refresh(job)
    assert tags.of(job) == ["buoys", "phase1"] and job.version == version

    node = next(n for n in pipeline_graph(db)["nodes"] if n["type"] == "job")
    assert node["tags"] == ["buoys", "phase1"]
