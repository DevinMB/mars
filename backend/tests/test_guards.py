"""Guardrail tests. Each case here corresponds to a way a stream job silently
damages something that is not itself."""
from __future__ import annotations

import json

import pytest

from app.guards import check_catalog_entry, check_job, parse_options, table_name
from app.models import CatalogEntry, Job


def kafka_source(topic: str, group: str | None) -> str:
    opts = [f"  'connector' = 'kafka'", f"  'topic' = '{topic}'"]
    if group:
        opts.append(f"  'properties.group.id' = '{group}'")
    return "CREATE TABLE IF NOT EXISTS `t` (\n  `doc` STRING\n) WITH (\n" + ",\n".join(opts) + "\n)"


def kafka_sink(topic: str) -> str:
    return (
        "CREATE TABLE IF NOT EXISTS `s` (`doc` STRING) WITH (\n"
        f"  'connector' = 'kafka',\n  'topic' = '{topic}'\n)"
    )


def couch_sink(db: str, mode: str = "kafka_key") -> str:
    return (
        "CREATE TABLE IF NOT EXISTS `c` (`doc` STRING) WITH (\n"
        f"  'connector' = 'couchdb',\n  'db' = '{db}',\n  'id.mode' = '{mode}'\n)"
    )


# -- parsing ---------------------------------------------------------------


def test_parse_options():
    o = parse_options(kafka_source("my-topic", "mars-x"))
    assert o["topic"] == "my-topic"
    assert o["properties.group.id"] == "mars-x"
    assert o["connector"] == "kafka"


def test_parse_handles_escaped_quotes():
    sql = "CREATE TABLE `t` (`a` INT) WITH ('connector'='kafka','x'='it''s here')"
    assert parse_options(sql)["x"] == "it's here"


def test_table_name():
    assert table_name(kafka_source("a", "mars-b")) == "t"
    assert table_name("CREATE TABLE `foo` (x INT)") == "foo"
    assert table_name("SELECT 1") is None


# -- single-entry checks ---------------------------------------------------


def test_unprefixed_consumer_group_is_a_danger():
    ws = check_catalog_entry(kafka_source("events-input", "events-sink"), "source", "kafka")
    codes = {w.code for w in ws}
    assert "kafka_group_collision" in codes
    danger = next(w for w in ws if w.code == "kafka_group_collision")
    assert danger.level == "danger"
    # The message must explain the actual consequence, not just say "bad".
    assert "silently stop receiving" in danger.message
    assert "mars-events-sink" in danger.message


def test_prefixed_consumer_group_is_clean():
    ws = check_catalog_entry(kafka_source("events-input", "mars-events-sink"), "source", "kafka")
    assert ws == []


def test_missing_consumer_group_warns_about_restarts():
    ws = check_catalog_entry(kafka_source("t", None), "source", "kafka")
    assert [w.code for w in ws] == ["kafka_no_group"]
    assert ws[0].level == "warning"


def test_couchdb_auto_id_warns_about_replays():
    ws = check_catalog_entry(couch_sink("events", "auto"), "sink", "couchdb")
    assert [w.code for w in ws] == ["couchdb_auto_id"]
    assert "duplicate documents" in ws[0].message


def test_couchdb_deterministic_id_is_clean():
    for mode in ("kafka_key", "timestamp", "field", "custom"):
        assert check_catalog_entry(couch_sink("events", mode), "sink", "couchdb") == []


def test_sink_group_id_is_not_checked():
    # group.id is meaningless on a sink; flagging it would be noise.
    assert check_catalog_entry(kafka_sink("out"), "sink", "kafka") == []


# -- job-level checks ------------------------------------------------------


@pytest.fixture
def job_with(db):
    def _make(name: str, entries: list[CatalogEntry]) -> Job:
        for e in entries:
            db.add(e)
        # How a job uses a table now comes from its SQL, so the SQL has to read
        # the entries meant as sources and write the ones meant as sinks.
        sinks = [e.name for e in entries if e.kind == "sink"]
        sources = [e.name for e in entries if e.kind != "sink"]
        reads = f"SELECT * FROM {sources[0]}" if sources else "SELECT 1"
        inserts = [f"INSERT INTO {s} {reads}" for s in sinks] or [reads]
        j = Job(
            name=name,
            sql_text="EXECUTE STATEMENT SET BEGIN " + "; ".join(inserts) + "; END",
            catalog_refs=json.dumps([e.name for e in entries]),
        )
        db.add(j)
        db.commit()
        return j

    return _make


def test_topic_loop_is_flagged(db, job_with):
    job = job_with("loop", [
        CatalogEntry(name="src", kind="source", connector="kafka",
                     sql_text=kafka_source("same-topic", "mars-a")),
        CatalogEntry(name="dst", kind="sink", connector="kafka",
                     sql_text=kafka_sink("same-topic")),
    ])
    ws = check_job(db, job)
    loop = next(w for w in ws if w.code == "topic_loop")
    assert loop.level == "danger"
    assert "grows without bound" in loop.message


def test_two_jobs_writing_one_topic_is_flagged(db, job_with):
    job_with("first", [
        CatalogEntry(name="out_a", kind="sink", connector="kafka",
                     sql_text=kafka_sink("device-status")),
    ])
    second = job_with("second", [
        CatalogEntry(name="out_b", kind="sink", connector="kafka",
                     sql_text=kafka_sink("device-status")),
    ])
    ws = check_job(db, second)
    shared = next(w for w in ws if w.code == "shared_output_topic")
    # This is the exact failure that would double-count sit-stats-api.
    assert "every record twice" in shared.message
    assert "first" in shared.message


def test_distinct_output_topics_are_clean(db, job_with):
    job_with("first", [
        CatalogEntry(name="out_a", kind="sink", connector="kafka",
                     sql_text=kafka_sink("device-status")),
    ])
    second = job_with("second", [
        CatalogEntry(name="out_b", kind="sink", connector="kafka",
                     sql_text=kafka_sink("device-status-flink")),
    ])
    assert [w.code for w in check_job(db, second)] == []


def test_two_couchdb_sinks_on_one_database_warn(db, job_with):
    job = job_with("fanout", [
        CatalogEntry(name="c1", kind="sink", connector="couchdb", sql_text=couch_sink("shared")),
        CatalogEntry(name="c2", kind="sink", connector="couchdb", sql_text=couch_sink("shared")),
    ])
    assert any(w.code == "shared_couchdb_target" for w in check_job(db, job))


def test_couchdb_fanout_to_distinct_databases_is_clean(db, job_with):
    job = job_with("fanout", [
        CatalogEntry(name="c1", kind="sink", connector="couchdb", sql_text=couch_sink("car-counts")),
        CatalogEntry(name="c2", kind="sink", connector="couchdb", sql_text=couch_sink("cat-weights")),
    ])
    assert [w.code for w in check_job(db, job)] == []


def test_dangers_are_listed_before_warnings(db, job_with):
    job = job_with("mixed", [
        CatalogEntry(name="src", kind="source", connector="kafka",
                     sql_text=kafka_source("t", "not-prefixed")),
        CatalogEntry(name="dst", kind="sink", connector="couchdb",
                     sql_text=couch_sink("x", "auto")),
    ])
    ws = check_job(db, job)
    assert len(ws) >= 2
    assert ws[0].level == "danger"


def test_job_without_catalog_refs_is_clean(db):
    j = Job(name="bare", sql_text="SELECT 1", catalog_refs="[]")
    db.add(j)
    db.commit()
    assert check_job(db, j) == []


def test_a_table_entry_is_checked_by_how_the_job_uses_it(db):
    """No stored role: writing it makes it a sink for the checks, reading it a source."""
    db.add(CatalogEntry(name="events", kind="table", connector="kafka",
                        sql_text=kafka_source("raw-events", "not-prefixed")))
    db.add(CatalogEntry(name="out", kind="table", connector="kafka",
                        sql_text=kafka_sink("raw-events")))
    job = Job(name="echo", sql_text="INSERT INTO out SELECT * FROM events",
              catalog_refs=json.dumps(["events", "out"]))
    db.add(job)
    db.commit()
    codes = {w.code for w in check_job(db, job)}
    assert "kafka_group_collision" in codes, "read as a source, so its group is checked"
    assert "topic_loop" in codes, "reads and writes raw-events"
