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


# -- consumer groups ---------------------------------------------------------

from app.guards import add_option, parse_options  # noqa: E402
from app.lineage import consumer_groups  # noqa: E402


def _kafka(name, topic, group=None):
    opts = f"'connector' = 'kafka', 'topic' = '{topic}'" + (f", 'properties.group.id' = '{group}'" if group else "")
    return CatalogEntry(name=name, kind="table", connector="kafka",
                        sql_text=f"-- feeds (with) things\nCREATE TABLE `{name}` (`doc` STRING) WITH ({opts})")


def test_unnamed_kafka_reads_get_the_jobs_group_and_named_ones_keep_theirs():
    entries = {e.name: e for e in [_kafka("a", "ta"), _kafka("b", "tb", "mars-mine"), _kafka("out", "to")]}
    job = Job(name="enrich", sql_text="INSERT INTO out SELECT * FROM a JOIN b ON true",
              catalog_refs=json.dumps(["a", "b", "out"]))
    groups = consumer_groups(job, entries)
    assert {n: (g.group, g.automatic) for n, g in groups.items()} == {
        "a": ("mars-enrich", True), "b": ("mars-mine", False)}  # out is written, not read


def test_two_unnamed_tables_on_one_topic_in_one_job_do_not_share_a_group():
    entries = {e.name: e for e in [_kafka("x1", "t"), _kafka("x2", "t")]}
    job = Job(name="j", sql_text="SELECT * FROM x1 JOIN x2 ON true", catalog_refs=json.dumps(["x1", "x2"]))
    assert sorted(g.group for g in consumer_groups(job, entries).values()) == ["mars-j-x1", "mars-j-x2"]


def test_add_option_inserts_into_the_with_clause_not_into_a_comment():
    sql = _kafka("a", "ta").sql_text
    out = add_option(sql, "properties.group.id", "mars-j")
    assert out.startswith("-- feeds (with) things")
    assert parse_options(out)["properties.group.id"] == "mars-j"
    assert parse_options(out)["topic"] == "ta"
    assert parse_options(add_option("CREATE TABLE t (x INT) WITH ()", "k", "v")) == {"k": "v"}


def test_the_submitted_script_carries_the_group_but_the_entry_does_not(db):
    from app.submitter import JobSubmitter

    entry = _kafka("a", "ta")
    db.add_all([entry, _kafka("b", "tb", "mars-mine")])
    job = Job(name="enrich", sql_text="SELECT * FROM a JOIN b ON true", catalog_refs=json.dumps(["a", "b"]))
    db.add(job)
    db.commit()
    script = JobSubmitter(None, None, None).build_script(db, job)
    assert parse_options(script[0])["properties.group.id"] == "mars-enrich"
    assert parse_options(script[1])["properties.group.id"] == "mars-mine"
    assert script[-1] == job.sql_text  # the job's SQL is never rewritten
    assert "group.id" not in db.get(CatalogEntry, entry.id).sql_text
