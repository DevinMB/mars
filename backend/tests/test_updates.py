"""Versions and updates, against a fake GitHub.

The console only reports: these check it reports the right thing on each channel,
says something useful when GitHub refuses, stays quiet when checking is off, and
gives update steps that say when a maintenance window is needed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app import updates
from app.routes import system

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
RUNNING = "a" * 40
NEWEST = "b" * 40


def commit(sha, title, date="2026-10-11T10:00:00Z"):
    return {"sha": sha, "commit": {"message": f"{title}\n\nbody", "committer": {"date": date}}}


def github(*, releases=True, tags=True, compare_status=200, auth_status=None, ahead=2):
    def handler(request: httpx.Request) -> httpx.Response:
        if auth_status:
            return httpx.Response(auth_status, json={"message": "Bad credentials"})
        p = request.url.path
        if p.endswith("/commits/main"):
            return httpx.Response(200, json={**commit(NEWEST, "Newest on main"),
                                             "html_url": "https://github.com/x/mars/commit/b"})
        if p.endswith("/releases/latest"):
            if not releases:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"tag_name": "v0.2.0", "published_at": "2026-10-10T00:00:00Z",
                                             "html_url": "https://github.com/x/mars/releases/tag/v0.2.0"})
        if p.endswith("/commits/v0.2.0"):
            return httpx.Response(200, json=commit(NEWEST, "Release v0.2.0"))
        if p.endswith("/tags"):
            return httpx.Response(200, json=[{"name": "v0.1.0", "commit": {"sha": NEWEST}}] if tags else [])
        if "/compare/" in p:
            if compare_status != 200:
                return httpx.Response(compare_status, json={})
            commits = [commit("c%d" % i + "0" * 38, f"Change {i}") for i in range(ahead)]
            return httpx.Response(200, json={"ahead_by": ahead, "commits": commits})
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    c = SimpleNamespace(
        data_dir=tmp_path, update_check=True, update_channel="main", update_repo="x/mars",
        update_token_secret="", revision=RUNNING, built_at="2026-10-01T00:00:00Z",
        flink_revision="", flink_image="ghcr.io/x/mars-flink@sha256:" + "f" * 64,
        console_image="ghcr.io/x/mars-console@sha256:" + "c" * 64, update_instructions="",
    )
    monkeypatch.setattr(updates, "settings", lambda: c)
    monkeypatch.setattr(system, "settings", lambda: c)
    return c


@pytest.mark.asyncio
async def test_main_channel_reports_commits_behind(cfg):
    r = await updates.check(now=NOW, transport=github(ahead=3))
    assert r.error is None
    assert r.latest.revision == NEWEST and r.latest.label == NEWEST[:7]
    assert r.console.behind_by == 3 and r.console.update_available
    assert [c.title for c in r.console.commits] == ["Change 2", "Change 1", "Change 0"]


@pytest.mark.asyncio
async def test_releases_channel_uses_the_latest_release(cfg):
    cfg.update_channel = "releases"
    r = await updates.check(now=NOW, transport=github())
    assert r.latest.label == "v0.2.0" and r.latest.revision == NEWEST


@pytest.mark.asyncio
async def test_no_releases_falls_back_to_the_newest_tag(cfg):
    cfg.update_channel = "releases"
    r = await updates.check(now=NOW, transport=github(releases=False))
    assert r.latest.label == "v0.1.0"


@pytest.mark.asyncio
async def test_up_to_date_is_not_an_update(cfg):
    r = await updates.check(now=NOW, transport=github(ahead=0))
    assert r.console.behind_by == 0 and not r.console.update_available


@pytest.mark.asyncio
async def test_unknown_running_commit_is_not_reported_as_behind(cfg):
    r = await updates.check(now=NOW, transport=github(compare_status=404))
    assert r.console.behind_by is None and not r.console.update_available


@pytest.mark.asyncio
async def test_flink_without_a_recorded_revision_is_unknown_not_behind(cfg):
    r = await updates.check(now=NOW, transport=github())
    assert r.flink.running is None and r.flink.behind_by is None


@pytest.mark.asyncio
async def test_refused_by_github_says_a_token_may_be_needed(cfg):
    r = await updates.check(now=NOW, transport=github(auth_status=404))
    assert r.latest is None and "read-only token" in r.error


@pytest.mark.asyncio
async def test_schedule_is_daily_and_off_by_default(cfg):
    assert updates.is_due(NOW)
    await updates.check(now=NOW, transport=github())
    assert not updates.is_due(NOW + timedelta(hours=23))
    assert updates.is_due(NOW + timedelta(hours=25))
    cfg.update_channel = "releases"
    assert updates.is_due(NOW + timedelta(hours=1)), "switching channel checks again"
    cfg.update_check = False
    assert not updates.is_due(NOW + timedelta(days=30))


@pytest.mark.asyncio
async def test_version_endpoint_gives_update_steps(cfg):
    cfg.flink_revision = RUNNING
    await updates.check(now=NOW, transport=github(ahead=2))
    out = system.version(None)
    assert out["console"]["update_available"] and out["flink"]["update_available"]
    console, flink = out["console"]["how_to_update"], out["flink"]["how_to_update"]
    assert not console["needs_window"] and flink["needs_window"]
    assert f"ghcr.io/x/mars-console:sha-{NEWEST}" in console["steps"][0]
    assert any("Stop and save state" in s for s in flink["steps"])


@pytest.mark.asyncio
async def test_installation_specific_instructions(cfg):
    cfg.update_instructions = "deploy.sh {component} {short}"
    await updates.check(now=NOW, transport=github())
    out = system.version(None)
    assert out["console"]["how_to_update"]["command"] == f"deploy.sh console {NEWEST[:7]}"


def test_nothing_is_reported_while_checking_is_off(cfg):
    cfg.update_check = False
    out = system.version(None)
    assert out["latest"] is None and "update_available" not in out["console"]
    assert out["console"]["revision"] == RUNNING
