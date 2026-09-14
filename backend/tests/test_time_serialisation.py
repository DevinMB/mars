"""Timestamps must leave the API unambiguous.

SQLite does not preserve tzinfo, so values read back are naive. Serialising them
bare gives strings like "2026-09-14T21:20:15", which a browser interprets as local
time -- and the console then reported every running job as having last run "in the
future", with a duration of 0s, for any client not on UTC.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas import RunOut, _as_utc_iso


def test_naive_datetime_is_labelled_utc():
    out = _as_utc_iso(datetime(2026, 9, 14, 21, 20, 15))
    assert out.endswith("+00:00"), out
    assert out.startswith("2026-09-14T21:20:15")


def test_aware_datetime_is_converted_not_relabelled():
    eastern = timezone(timedelta(hours=-4))
    out = _as_utc_iso(datetime(2026, 9, 14, 17, 20, 15, tzinfo=eastern))
    # The same instant, expressed in UTC.
    assert out.startswith("2026-09-14T21:20:15")
    assert out.endswith("+00:00")


def test_run_payload_carries_a_zone():
    run = RunOut(
        id=1, job_version=1, flink_job_id="a" * 32, state="running",
        started_at=datetime(2026, 9, 14, 21, 20, 15), ended_at=None,
        error_summary=None, restarts=0, triggered_by_schedule=False,
        submitted_by="admin",
    )
    payload = run.model_dump(mode="json")
    assert payload["started_at"].endswith("+00:00")
    assert payload["ended_at"] is None


def test_a_recent_timestamp_is_not_in_the_future():
    """The regression, stated directly: parsed back, a just-now timestamp must not
    land ahead of now."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # as SQLite returns it
    parsed = datetime.fromisoformat(_as_utc_iso(now))
    assert parsed <= datetime.now(timezone.utc) + timedelta(seconds=2)
    assert parsed >= datetime.now(timezone.utc) - timedelta(minutes=1)
