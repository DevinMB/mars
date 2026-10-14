"""The pipeline graph: jobs joined through the topics and tables they share."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import lineage
from app.models import CatalogEntry, ExternalEndpoint, Job, JobRun, RunState
from app.routes import pipeline as routes

TOPIC_KEY = "kafka:k:9092/events"


def kafka(topic):
    return (f"CREATE TABLE t (doc STRING) WITH ('connector' = 'kafka', 'topic' = '{topic}', "
            "'properties.bootstrap.servers' = 'k:9092')")


@pytest.fixture
def home(db):
    # One topic described by two entries: one written, one read.
    db.add(CatalogEntry(name="events_out", kind="table", connector="kafka", sql_text=kafka("events")))
    db.add(CatalogEntry(name="events_in", kind="table", connector="kafka", sql_text=kafka("events")))
    db.add(CatalogEntry(name="raw", kind="table", connector="kafka", sql_text=kafka("raw")))
    db.add(CatalogEntry(name="spare", kind="table", connector="kafka", sql_text=kafka("spare")))
    enrich = Job(name="enrich", sql_text="INSERT INTO events_out SELECT * FROM raw",
                 catalog_refs='["raw", "events_out"]')
    archive = Job(name="archive", sql_text="INSERT INTO x SELECT * FROM events_in",
                  catalog_refs='["events_in"]')
    db.add_all([enrich, archive])
    db.flush()
    db.add(JobRun(job_id=enrich.id, job_version=1, state=RunState.FAILED.value))
    db.commit()
    return db


def edges(graph):
    return {(e["from"], e["to"]) for e in graph["edges"]}


def test_jobs_connect_through_one_node_per_topic(home):
    g = lineage.pipeline_graph(home)
    topic = next(n for n in g["nodes"] if n["type"] == "resource" and n["label"] == "events")
    assert topic["entries"] == ["events_in", "events_out"], "two entries, one topic"
    assert ("job:enrich", topic["id"]) in edges(g)
    assert (topic["id"], "job:archive") in edges(g)
    raw = next(n for n in g["nodes"] if n.get("label") == "raw")
    assert (raw["id"], "job:enrich") in edges(g)


def test_job_state_and_unused_entries(home):
    g = lineage.pipeline_graph(home)
    jobs = {n["label"]: n for n in g["nodes"] if n["type"] == "job"}
    assert jobs["enrich"]["state"] == "failed" and jobs["archive"]["state"] is None
    assert g["unused"] == ["spare"]


def test_declared_producers_and_consumers_attach_to_their_topic(home):
    home.add(ExternalEndpoint(resource_key="kafka:k:9092/raw", name="collector", direction="produces"))
    home.add(ExternalEndpoint(resource_key=TOPIC_KEY, name="stats-api", direction="consumes"))
    home.commit()
    g = lineage.pipeline_graph(home)
    ext = {n["label"]: n["id"] for n in g["nodes"] if n["type"] == "external"}
    assert (ext["collector"], "res:kafka:k:9092/raw") in edges(g)
    assert (f"res:{TOPIC_KEY}", ext["stats-api"]) in edges(g)


def test_an_unused_topic_with_an_outside_reader_still_appears(home):
    home.add(ExternalEndpoint(resource_key="kafka:k:9092/spare", name="auditor", direction="consumes"))
    home.commit()
    g = lineage.pipeline_graph(home)
    assert any(n.get("label") == "spare" for n in g["nodes"])
    assert "spare" not in g["unused"]


def test_an_endpoint_whose_topic_is_gone_is_left_out(home):
    home.add(ExternalEndpoint(resource_key="kafka:k:9092/deleted", name="ghost", direction="produces"))
    home.commit()
    assert not any(n.get("label") == "ghost" for n in lineage.pipeline_graph(home)["nodes"])


def test_declaring_an_endpoint_needs_a_known_topic(home):
    principal = type("P", (), {"username": "operator"})()
    with pytest.raises(HTTPException) as exc:
        routes.add_external(routes.ExternalIn(resource_key="kafka:k:9092/nope", name="x", direction="produces"),
                            principal, home, None)
    assert exc.value.status_code == 404
    out = routes.add_external(routes.ExternalIn(resource_key=TOPIC_KEY, name=" stats-api ", direction="consumes"),
                              principal, home, None)
    assert home.get(ExternalEndpoint, out["id"]).name == "stats-api"


def test_only_writers_change_the_pipeline():
    from app.deps import require_writer

    guards = {
        (tuple(sorted(r.methods)), r.path): [d.call for d in r.dependant.dependencies]
        for r in routes.router.routes
    }
    for (methods, path), deps in guards.items():
        if "GET" not in methods:
            assert require_writer in deps, f"{methods} {path} must require a writer"
