"""Which tables a job reads and writes, and what a table points at.

The plan lines are real EXPLAIN output from Flink 2.2.1 (a statement set writing
three CouchDB tables from one Kafka topic), so a parser that passes here parses
what Flink actually prints.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from app import lineage
from app.models import CatalogEntry, Job

FANOUT_PLAN = """
LogicalSink(table=[default_catalog.default_database.car_counts_sink], fields=[doc, record_key])
LogicalSink(table=[default_catalog.default_database.cat_weights_sink], fields=[doc, record_key])
Sink(table=[default_catalog.default_database.car_counts_sink], fields=[doc, record_key])
+- TableSourceScan(table=[[default_catalog, default_database, ha_metrics_raw]], fields=[record_key, doc])
Sink(table=[default_catalog.default_database.cat_weights_sink], fields=[doc, record_key])
TableSourceScan(table=[[default_catalog, default_database, ha_metrics_raw]], fields=[record_key, doc])(reuse_id=[1])
"""
FANOUT_REFS = ["ha_metrics_raw", "car_counts_sink", "cat_weights_sink"]


def kafka(topic, servers="kafka:9092"):
    return (f"CREATE TABLE t (doc STRING) WITH ('connector' = 'kafka', 'topic' = '{topic}', "
            f"'properties.bootstrap.servers' = '{servers}')")


# -- from SQL -----------------------------------------------------------------

def test_sql_insert_is_a_write_and_the_rest_are_reads():
    u = lineage.usage_from_sql("INSERT INTO sink SELECT * FROM src", ["src", "sink"])
    assert u.writes == {"sink"} and u.reads == {"src"} and u.source == "sql"


def test_sql_statement_set_backticks_and_qualified_names():
    sql = """EXECUTE STATEMENT SET BEGIN
      INSERT INTO `a_sink` SELECT * FROM src;
      INSERT INTO default_catalog.default_database.b_sink SELECT * FROM src;
      -- INSERT INTO commented_out SELECT 1
    END;"""
    u = lineage.usage_from_sql(sql, ["src", "a_sink", "b_sink", "commented_out"])
    assert u.writes == {"a_sink", "b_sink"}
    assert u.reads == {"src", "commented_out"}


def test_sql_reading_and_writing_one_table_is_both():
    u = lineage.usage_from_sql("INSERT INTO t SELECT * FROM t", ["t"])
    assert u.reads == {"t"} and u.writes == {"t"}


# -- from Flink's plan ---------------------------------------------------------

def test_plan_names_every_read_and_write():
    u = lineage.usage_from_plan(FANOUT_PLAN, FANOUT_REFS)
    assert u.reads == {"ha_metrics_raw"}
    assert u.writes == {"car_counts_sink", "cat_weights_sink"}
    assert u.source == "plan"


def test_plan_lookup_join_is_a_read():
    plan = "LookupJoin(table=[default_catalog.default_database.dim], joinType=[InnerJoin])"
    assert lineage.usage_from_plan(plan, ["dim"]).reads == {"dim"}


def test_plan_ignores_tables_outside_the_catalog():
    plan = "TableSourceScan(table=[[default_catalog, default_database, temp_view_src]])"
    assert lineage.usage_from_plan(plan, ["other"]).reads == set()


def test_stored_plan_is_used_only_while_the_sql_is_unchanged():
    job = Job(name="j", sql_text="INSERT INTO car_counts_sink SELECT * FROM ha_metrics_raw",
              catalog_refs=json.dumps(FANOUT_REFS))
    lineage.record_plan(job, [FANOUT_PLAN])
    assert lineage.job_usage(job).source == "plan"
    assert lineage.job_usage(job).writes == {"car_counts_sink", "cat_weights_sink"}

    job.sql_text = "INSERT INTO cat_weights_sink SELECT * FROM ha_metrics_raw"
    u = lineage.job_usage(job)
    assert u.source == "sql" and u.writes == {"cat_weights_sink"}


def test_editor_plans_are_recalled_by_fingerprint():
    job = Job(name="j", sql_text="INSERT INTO b SELECT * FROM a", catalog_refs='["a","b"]')
    lineage.remember_plans(job, ["plan text"])
    assert lineage.recall_plans(job) == ["plan text"]
    job.sql_text = "INSERT INTO b SELECT 1"
    assert lineage.recall_plans(job) is None


# -- what a table points at ------------------------------------------------------

def test_entries_on_one_kafka_topic_share_a_resource():
    a = CatalogEntry(name="raw", connector="kafka", sql_text=kafka("raw-sit-topic"))
    b = CatalogEntry(name="timed", connector="kafka", sql_text=kafka("raw-sit-topic"))
    c = CatalogEntry(name="other_cluster", connector="kafka", sql_text=kafka("raw-sit-topic", "other:9092"))
    ra, rb, rc = (lineage.resource_of(e) for e in (a, b, c))
    assert ra.key == rb.key and ra.kind == "kafka topic" and ra.label == "raw-sit-topic"
    assert rc.key != ra.key, "another Kafka cluster's topic of the same name is a different topic"


def test_couchdb_groups_by_server_and_database():
    sql = "CREATE TABLE t (d STRING) WITH ('connector' = 'couchdb', 'url' = 'http://c:5984', 'db' = 'sits')"
    r = lineage.resource_of(CatalogEntry(name="sits_sink", connector="couchdb", sql_text=sql))
    assert r.kind == "couchdb database" and r.label == "sits"


def test_unknown_connector_is_its_own_resource():
    r = lineage.resource_of(CatalogEntry(name="ha_light", connector="home-assistant",
                                         sql_text="CREATE TABLE t (a STRING) WITH ('connector' = 'home-assistant')"))
    assert r.key == "table:ha_light"


def test_a_manifest_can_declare_what_its_tables_point_at():
    registry = SimpleNamespace(get=lambda name: SimpleNamespace(
        identity={"server": "base-url", "name": "domain", "label": "home assistant domain"}))
    sql = ("CREATE TABLE t (a STRING) WITH ('connector' = 'home-assistant', "
           "'base-url' = 'http://ha:8123', 'domain' = 'light')")
    r = lineage.resource_of(CatalogEntry(name="ha_light", connector="home-assistant", sql_text=sql), registry)
    assert r.kind == "home assistant domain" and r.label == "light"


# -- the catalog view -----------------------------------------------------------

def test_catalog_usage_lists_readers_and_writers(db):
    for name in ("raw", "enriched"):
        db.add(CatalogEntry(name=name, kind="table", connector="kafka", sql_text=kafka(name)))
    db.add(Job(name="enrich", sql_text="INSERT INTO enriched SELECT * FROM raw",
               catalog_refs='["raw", "enriched"]'))
    db.add(Job(name="archive", sql_text="INSERT INTO nowhere SELECT * FROM enriched",
               catalog_refs='["enriched"]'))
    db.commit()
    usage = lineage.catalog_usage(db)
    assert usage["raw"].read_by == ["enrich"] and usage["raw"].written_by == []
    assert usage["enriched"].written_by == ["enrich"] and usage["enriched"].read_by == ["archive"]


def test_role_hint_for_drafting():
    reg = SimpleNamespace(get=lambda n: {"datagen": SimpleNamespace(kinds=["source"]),
                                         "couchdb": SimpleNamespace(kinds=["sink"]),
                                         "kafka": SimpleNamespace(kinds=["source", "sink"])}.get(n))
    hint = lambda kind, conn: lineage.role_hint(CatalogEntry(name="x", kind=kind, connector=conn), reg)  # noqa: E731
    assert hint("source", "kafka") == "source", "an older entry keeps its stored role"
    assert hint("table", "datagen") == "source"
    assert hint("table", "couchdb") == "sink"
    assert hint("table", "kafka") == "table"
