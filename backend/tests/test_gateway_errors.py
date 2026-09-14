"""The error reducer decides what a user sees when a job will not compile. A bad
reducer means every failure looks like a 9kB Java trace, which is the single
fastest way to make a tool feel unusable."""
from __future__ import annotations

import json

from app.gateway import _friendly_error

# Shape captured from a real Flink 2.2.1 SQL Gateway response.
REAL_BODY = json.dumps(
    {
        "errors": [
            "Internal server error.",
            "<Exception on server side:\n"
            "org.apache.flink.table.gateway.api.utils.SqlGatewayException: "
            "org.apache.flink.table.gateway.api.utils.SqlGatewayException: Failed to fetchResults.\n"
            "\tat org.apache.flink.table.gateway.service.SqlGatewayServiceImpl.fetchResults(x.java:238)\n"
            "\t... 48 more\n"
            "Caused by: org.apache.flink.table.gateway.api.utils.SqlGatewayException: "
            "Failed to fetchResults.\n"
            "\tat org.apache.flink.x.y(z.java:1)\n"
            "Caused by: org.apache.flink.table.gateway.service.utils.SqlExecutionException: "
            "Failed to execute the operation 647bb259.\n"
            "\tat org.apache.flink.x.y(z.java:2)\n"
            "Caused by: org.apache.flink.table.api.ValidationException: Cannot find table "
            "'`default_catalog`.`default_database`.`nowhere`' in any of the catalogs "
            "[default_catalog], nor as a temporary table.\n"
            "\tat org.apache.flink.x.y(z.java:3)\n"
            "End of exception on server side>",
        ]
    }
)


def test_extracts_the_deepest_cause():
    msg = _friendly_error(REAL_BODY)
    assert "Cannot find table" in msg
    assert "nowhere" in msg
    # Outer plumbing frames must not be what the user reads.
    assert "fetchResults" not in msg
    assert "SqlExecutionException" not in msg


def test_strips_constant_catalog_noise():
    msg = _friendly_error(REAL_BODY)
    assert "default_catalog" not in msg
    assert "default_database" not in msg
    assert "`nowhere`" in msg


def test_no_stack_frames_survive():
    msg = _friendly_error(REAL_BODY)
    assert "\tat " not in msg
    assert ".java:" not in msg


def test_result_is_short_enough_to_show_inline():
    assert len(_friendly_error(REAL_BODY)) <= 400


def test_handles_non_json_body():
    msg = _friendly_error("plain text failure")
    assert msg == "plain text failure"


def test_handles_empty_body():
    assert _friendly_error("") == "Statement failed with no detail"


def test_handles_json_without_errors_key():
    assert _friendly_error(json.dumps({"something": "else"}))


def test_single_string_errors_field():
    body = json.dumps({"errors": "Table 'x' does not exist"})
    assert "Table 'x' does not exist" in _friendly_error(body)


def test_validation_exception_without_caused_by():
    body = json.dumps({
        "errors": [
            "org.apache.flink.table.api.ValidationException: "
            "Unsupported options found for 'couchdb'.\n\tat org.x.y(z.java:1)"
        ]
    })
    msg = _friendly_error(body)
    assert "Unsupported options found" in msg
    assert "\tat " not in msg


def test_whitespace_is_collapsed():
    body = json.dumps({"errors": [
        "Caused by: org.apache.flink.table.api.ValidationException: line one\n"
        "   continued    here\n\tat org.x(y.java:1)"
    ]})
    msg = _friendly_error(body)
    assert "  " not in msg
