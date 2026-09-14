"""End-to-end: a stored job with secret references becomes a running Flink job.

Requires the MARS stack and a reachable CouchDB. Run with:
    pytest tests/integration -o addopts='' -v
"""
from __future__ import annotations

import json
import os
import time

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cluster import FlinkClusterClient
from app.db import Base
from app.ddl import Column, build_create_table
from app.gateway import SqlGatewayClient
from app.models import CatalogEntry, Job, JobType
from app.registry import ConnectorRegistry
from app.secrets import SecretStore
from app.submitter import JobSubmitter

from pathlib import Path

GATEWAY = os.environ["MARS_SQL_GATEWAY_URL"]
FLINK = os.environ["MARS_FLINK_REST_URL"]
COUCH = os.environ["COUCH_URL"]
COUCH_USER = os.environ["COUCH_USER"]
COUCH_PASS = os.environ["COUCH_PASS"]
DB_NAME = "mars-itest"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


@pytest.fixture
def store():
    return SecretStore(key=Fernet.generate_key())


@pytest.fixture
def registry():
    r = ConnectorRegistry(
        bundled_dir=Path(__file__).resolve().parents[2] / "manifests",
        jar_dir=Path("/jars"),
    )
    r.load()
    return r


@pytest.fixture
def couch_db():
    auth = (COUCH_USER, COUCH_PASS)
    httpx.delete(f"{COUCH}/{DB_NAME}", auth=auth, timeout=30)
    r = httpx.put(f"{COUCH}/{DB_NAME}", auth=auth, timeout=30)
    assert r.status_code in (201, 412), r.text
    yield DB_NAME
    httpx.delete(f"{COUCH}/{DB_NAME}", auth=auth, timeout=30)


@pytest.mark.asyncio
async def test_job_with_secrets_runs_and_writes(db, store, registry, couch_db):
    store.put(db, "couch_user", COUCH_USER)
    store.put(db, "couch_pass", COUCH_PASS)
    db.commit()

    source_sql = build_create_table(
        "itest_src", registry.get("datagen"),
        {"number-of-rows": "25"},
        [Column("id", "INT"), Column("label", "STRING")],
    )
    sink_sql = build_create_table(
        "itest_sink", registry.get("couchdb"),
        {
            "url": COUCH,
            "db": couch_db,
            "username": "${secret:couch_user}",
            "password": "${secret:couch_pass}",
            "id.mode": "kafka_key",
            "sink.batch.size": "5",
        },
        [Column("doc", "STRING"), Column("kafka_key", "STRING")],
    )

    # The generated sink DDL must carry placeholders, never the real password.
    assert "${secret:couch_pass}" in sink_sql
    assert COUCH_PASS not in sink_sql

    db.add(CatalogEntry(name="itest_src", kind="source", connector="datagen", sql_text=source_sql))
    db.add(CatalogEntry(name="itest_sink", kind="sink", connector="couchdb", sql_text=sink_sql))

    job = Job(
        name="itest_job",
        job_type=JobType.BATCH.value,
        catalog_refs=json.dumps(["itest_src", "itest_sink"]),
        sql_text=(
            "INSERT INTO itest_sink "
            "SELECT JSON_OBJECT('id' VALUE id, 'label' VALUE label), "
            "CONCAT('itest-', CAST(id AS STRING)) FROM itest_src"
        ),
    )
    db.add(job)
    db.commit()

    submitter = JobSubmitter(
        SqlGatewayClient(GATEWAY, timeout=90),
        FlinkClusterClient(FLINK),
        store,
    )

    # The previewable script must still be free of plaintext credentials.
    script = submitter.build_script(db, job)
    assert any("${secret:couch_pass}" in s for s in script)
    assert not any(COUCH_PASS in s for s in script)

    run = await submitter.submit(db, job, submitted_by="itest")
    assert run.flink_job_id, "no Flink job id recorded"
    assert run.state == "running"

    # Wait for the bounded job to finish.
    cluster = FlinkClusterClient(FLINK)
    deadline = time.time() + 120
    state = None
    while time.time() < deadline:
        o = await cluster.get_job(run.flink_job_id)
        state = o.state if o else None
        if o and o.is_terminal:
            break
        time.sleep(2)
    assert state == "FINISHED", f"job ended in state {state}"

    docs = httpx.get(f"{COUCH}/{couch_db}", auth=(COUCH_USER, COUCH_PASS), timeout=30).json()
    assert docs["doc_count"] == 25, docs

    # Stored records must never have absorbed the resolved credentials.
    entry = db.query(CatalogEntry).filter_by(name="itest_sink").one()
    assert COUCH_PASS not in entry.sql_text
    assert db.query(Job).filter_by(name="itest_job").one().sql_text.count(COUCH_PASS) == 0

    await submitter.refresh_states(db)
    db.refresh(run)
    assert run.state == "finished"
    assert run.ended_at is not None


@pytest.mark.asyncio
async def test_validate_rejects_bad_sql_without_submitting(db, store, registry):
    job = Job(name="bad", sql_text="INSERT INTO nowhere SELECT 1", catalog_refs="[]")
    db.add(job)
    db.commit()

    submitter = JobSubmitter(
        SqlGatewayClient(GATEWAY, timeout=60), FlinkClusterClient(FLINK), store
    )

    from app.submitter import SubmissionError

    before = len(await FlinkClusterClient(FLINK).list_jobs())
    with pytest.raises(SubmissionError) as exc:
        await submitter.validate(db, job)

    # The message should name the missing object, not hand over a Java trace.
    assert "nowhere" in str(exc.value).lower()
    assert len(await FlinkClusterClient(FLINK).list_jobs()) == before


@pytest.mark.asyncio
async def test_missing_secret_is_reported_before_anything_runs(db, store, registry):
    job = Job(
        name="needs_secret",
        sql_text="INSERT INTO t SELECT '${secret:not_defined}'",
        catalog_refs="[]",
    )
    db.add(job)
    db.commit()

    submitter = JobSubmitter(
        SqlGatewayClient(GATEWAY, timeout=60), FlinkClusterClient(FLINK), store
    )
    from app.submitter import SubmissionError

    with pytest.raises(SubmissionError, match="not_defined"):
        await submitter.submit(db, job)
