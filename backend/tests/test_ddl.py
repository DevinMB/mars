"""DDL generation takes option values straight from an HTTP request and puts them
inside a SQL string literal, so the escaping and validation here are a security
boundary, not a formatting nicety."""
from __future__ import annotations

import pytest

from app.ddl import (
    Column,
    DdlError,
    build_create_table,
    escape_option_value,
    split_statements,
)
from app.registry import ConnectorRegistry
from pathlib import Path


@pytest.fixture(scope="module")
def registry() -> ConnectorRegistry:
    r = ConnectorRegistry(
        bundled_dir=Path(__file__).resolve().parents[1] / "manifests",
        jar_dir=Path("/nonexistent"),
    )
    r.load()
    return r


@pytest.fixture
def kafka(registry):
    return registry.get("kafka")


def test_generates_expected_shape(kafka):
    sql = build_create_table(
        "whispers_raw",
        kafka,
        {
            "topic": "whispererer-log",
            "properties.bootstrap.servers": "192.168.1.250:9092",
            "properties.group.id": "mars-whispers",
            "format": "json",
        },
        [Column("doc", "STRING"), Column("kafka_key", "STRING")],
    )

    assert sql.startswith("CREATE TABLE IF NOT EXISTS `whispers_raw` (")
    assert "`doc` STRING" in sql
    assert "'connector' = 'kafka'" in sql
    assert "'topic' = 'whispererer-log'" in sql
    assert "'properties.group.id' = 'mars-whispers'" in sql


def test_defaults_are_omitted_to_keep_sql_readable(kafka):
    sql = build_create_table(
        "t", kafka,
        {"topic": "x", "properties.bootstrap.servers": "b:9092",
         "format": "json", "scan.startup.mode": "group-offsets"},
        [Column("doc", "STRING")],
    )
    # group-offsets is the documented default; emitting it adds noise only.
    assert "scan.startup.mode" not in sql
    assert "'format' = 'json'" in sql


def test_blank_options_are_dropped(kafka):
    sql = build_create_table(
        "t", kafka,
        {"topic": "x", "properties.bootstrap.servers": "b:9092", "format": "json",
         "properties.group.id": "   "},
        [Column("doc", "STRING")],
    )
    assert "group.id" not in sql


def test_missing_required_option_names_it(kafka):
    with pytest.raises(DdlError, match="requires: topic"):
        build_create_table("t", kafka, {"properties.bootstrap.servers": "b", "format": "json"},
                           [Column("doc", "STRING")])


def test_unknown_option_is_rejected(kafka):
    # Catching a typo at creation beats a Flink error minutes later.
    with pytest.raises(DdlError, match="Unknown option"):
        build_create_table(
            "t", kafka,
            {"topic": "x", "properties.bootstrap.servers": "b", "format": "json",
             "tpoic": "typo"},
            [Column("doc", "STRING")],
        )


def test_quote_in_option_value_cannot_break_out(kafka):
    sql = build_create_table(
        "t", kafka,
        {"topic": "x", "properties.bootstrap.servers": "b:9092", "format": "json",
         "properties.sasl.jaas.config": "user='ad''min' pw='x'"},
        [Column("doc", "STRING")],
    )
    # Every embedded quote must be doubled, leaving the literal balanced.
    body = sql.split("WITH (", 1)[1]
    assert body.count("'") % 2 == 0
    assert "ad''''min" in sql or "''" in sql


@pytest.mark.parametrize("bad", ["a'; DROP TABLE x --", "a\nb", "a\rb"])
def test_dangerous_option_values(kafka, bad):
    if "\n" in bad or "\r" in bad:
        with pytest.raises(DdlError, match="newlines"):
            escape_option_value(bad)
    else:
        # A quote is escaped rather than rejected; it stays inside the literal.
        assert escape_option_value(bad) == bad.replace("'", "''")


@pytest.mark.parametrize("bad", ["1table", "has-dash", "has space", "has`tick", "", "a" * 200])
def test_invalid_table_names_rejected(kafka, bad):
    with pytest.raises(DdlError, match="not a valid table name"):
        build_create_table(bad, kafka,
                           {"topic": "x", "properties.bootstrap.servers": "b", "format": "json"},
                           [Column("doc", "STRING")])


@pytest.mark.parametrize("bad", ["1col", "has-dash", "has`tick", "col;drop"])
def test_invalid_column_names_rejected(kafka, bad):
    with pytest.raises(DdlError, match="not a valid column name"):
        build_create_table("t", kafka,
                           {"topic": "x", "properties.bootstrap.servers": "b", "format": "json"},
                           [Column(bad, "STRING")])


def test_invalid_column_type_rejected(kafka):
    with pytest.raises(DdlError, match="not a recognised column type"):
        build_create_table("t", kafka,
                           {"topic": "x", "properties.bootstrap.servers": "b", "format": "json"},
                           [Column("c", "STRING; DROP TABLE x")])


def test_complex_column_types_allowed(kafka):
    sql = build_create_table(
        "t", kafka,
        {"topic": "x", "properties.bootstrap.servers": "b", "format": "json"},
        [Column("tags", "ARRAY<STRING>"), Column("meta", "MAP<STRING, STRING>"),
         Column("amount", "DECIMAL(10, 2)")],
    )
    assert "ARRAY<STRING>" in sql
    assert "MAP<STRING, STRING>" in sql
    assert "DECIMAL(10, 2)" in sql


def test_table_needs_columns(kafka):
    with pytest.raises(DdlError, match="at least one column"):
        build_create_table("t", kafka,
                           {"topic": "x", "properties.bootstrap.servers": "b", "format": "json"}, [])


# -- statement splitting ----------------------------------------------------


def test_split_basic():
    assert split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_split_ignores_semicolons_inside_strings():
    # A Kafka JAAS config contains semicolons; naive splitting corrupts it.
    script = (
        "CREATE TABLE a (x INT) WITH ("
        "'properties.sasl.jaas.config' = 'org.apache.kafka.PlainLoginModule required "
        "username=\"u\" password=\"p\";'); SELECT 1;"
    )
    parts = split_statements(script)
    assert len(parts) == 2
    assert "PlainLoginModule" in parts[0]
    assert parts[1] == "SELECT 1"


def test_split_handles_escaped_quotes():
    parts = split_statements("INSERT INTO t VALUES ('it''s fine; really'); SELECT 2")
    assert len(parts) == 2
    assert "it''s fine; really" in parts[0]


def test_split_ignores_semicolons_in_comments():
    script = "-- a comment; with semicolon\nSELECT 1;\n/* block; comment */ SELECT 2"
    parts = split_statements(script)
    assert len(parts) == 2


def test_split_handles_backticked_identifiers():
    parts = split_statements("SELECT `weird;name` FROM t; SELECT 2")
    assert len(parts) == 2
    assert "weird;name" in parts[0]


def test_split_tolerates_missing_trailing_semicolon():
    assert split_statements("SELECT 1") == ["SELECT 1"]
    assert split_statements("  ") == []
