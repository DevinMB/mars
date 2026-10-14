"""What this installation runs, and whether something newer exists.

The console only reports. It never updates itself: replacing containers needs
control of the host's container runtime, which is root on that host, and the
console deliberately has no such access. So an update notice comes with the
steps to take, not a button.

What it runs: MARS_REVISION and MARS_BUILT_AT are stamped into the console image
by the release build. The Flink image's commit cannot be read from inside the
console, so it comes from MARS_FLINK_REVISION when the deployment records it;
otherwise only the pinned image (MARS_FLINK_IMAGE) is known.

What's newest: off unless MARS_UPDATE_CHECK is true, since it is an outbound
request from your network. Once a day, GitHub is asked for the newest tagged
release (channel "releases") or the newest commit on main (channel "main"), and
for the commits between that and what is running. A private repository needs a
read-only token, stored as a MARS secret named by MARS_UPDATE_TOKEN_SECRET.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from .db import session_scope
from .secrets import SecretError, SecretStore
from .settings import settings

log = logging.getLogger(__name__)

API = "https://api.github.com"
CHECK_EVERY = timedelta(days=1)
MAX_COMMITS = 25


@dataclass
class Commit:
    sha: str
    title: str
    date: str


@dataclass
class Latest:
    revision: str  # the commit the newest release points at
    label: str  # tag name, or the short commit on main
    published_at: str | None
    url: str


@dataclass
class ComponentStatus:
    running: str | None  # commit, when known
    behind_by: int | None  # commits the newest release has that this lacks
    commits: list[Commit] = field(default_factory=list)

    @property
    def update_available(self) -> bool:
        return bool(self.behind_by)


@dataclass
class CheckResult:
    checked_at: str
    channel: str
    latest: Latest | None = None
    console: ComponentStatus | None = None
    flink: ComponentStatus | None = None
    error: str | None = None


def result_path() -> Path:
    return settings().data_dir / "update-check.json"


def last_result() -> CheckResult | None:
    try:
        raw = json.loads(result_path().read_text())
    except (OSError, ValueError):
        return None

    def component(d):
        if not d:
            return None
        return ComponentStatus(d["running"], d["behind_by"], [Commit(**c) for c in d.get("commits", [])])

    return CheckResult(
        checked_at=raw["checked_at"], channel=raw["channel"],
        latest=Latest(**raw["latest"]) if raw.get("latest") else None,
        console=component(raw.get("console")), flink=component(raw.get("flink")),
        error=raw.get("error"),
    )


def is_due(now: datetime) -> bool:
    if not settings().update_check:
        return False
    last = last_result()
    if last is None or last.channel != settings().update_channel:
        return True
    return datetime.fromisoformat(last.checked_at) + CHECK_EVERY <= now


def _token() -> str | None:
    name = settings().update_token_secret
    if not name:
        return None
    try:
        with session_scope() as db:
            return SecretStore().reveal(db, name)
    except SecretError as exc:
        raise RuntimeError(f"Update check token secret '{name}': {exc}") from exc


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = _token()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _latest(c: httpx.AsyncClient, repo: str, channel: str) -> Latest:
    if channel == "main":
        r = await c.get(f"{API}/repos/{repo}/commits/main")
        r.raise_for_status()
        d = r.json()
        return Latest(revision=d["sha"], label=d["sha"][:7],
                      published_at=d["commit"]["committer"]["date"], url=d["html_url"])
    r = await c.get(f"{API}/repos/{repo}/releases/latest")
    if r.status_code == 404:
        # No published releases: fall back to the newest tag.
        t = await c.get(f"{API}/repos/{repo}/tags", params={"per_page": 1})
        t.raise_for_status()
        tags = t.json()
        if not tags:
            raise RuntimeError(f"{repo} has no releases or tags yet.")
        tag = tags[0]
        return Latest(revision=tag["commit"]["sha"], label=tag["name"], published_at=None,
                      url=f"https://github.com/{repo}/releases/tag/{tag['name']}")
    r.raise_for_status()
    d = r.json()
    ref = await c.get(f"{API}/repos/{repo}/commits/{d['tag_name']}")
    ref.raise_for_status()
    return Latest(revision=ref.json()["sha"], label=d["tag_name"],
                  published_at=d.get("published_at"), url=d["html_url"])


# The files the Flink image is built from: its Dockerfile, and the pin naming its
# connector JARs. Most commits change only the console, docs or CI, and flink/conf
# is mounted from the checkout rather than built in; counting any of those as a
# Flink update would ask for a maintenance window that changes nothing.
FLINK_PATHS = ("flink/Dockerfile", "flink/connectors.image")


async def _touching(c: httpx.AsyncClient, repo: str, latest: str, paths: tuple[str, ...]) -> set[str]:
    """Commits up to latest that changed any of paths (recent history is enough)."""
    shas: set[str] = set()
    for path in paths:
        r = await c.get(f"{API}/repos/{repo}/commits", params={"sha": latest, "path": path, "per_page": 100})
        r.raise_for_status()
        shas |= {x["sha"] for x in r.json()}
    return shas


async def _compare(
    c: httpx.AsyncClient, repo: str, running: str | None, latest: str,
    only_paths: tuple[str, ...] | None = None,
) -> ComponentStatus:
    if not running:
        return ComponentStatus(running=None, behind_by=None)
    r = await c.get(f"{API}/repos/{repo}/compare/{running}...{latest}")
    if r.status_code == 404:
        # A commit GitHub has never seen: a local build, or a fork.
        return ComponentStatus(running=running, behind_by=None)
    r.raise_for_status()
    d = r.json()
    raw = list(reversed(d.get("commits", [])))
    behind = d.get("ahead_by", 0)
    if only_paths and raw:
        relevant = await _touching(c, repo, latest, only_paths)
        raw = [x for x in raw if x["sha"] in relevant]
        behind = len(raw)
    commits = [
        Commit(sha=x["sha"], title=x["commit"]["message"].splitlines()[0][:200],
               date=x["commit"]["committer"]["date"])
        for x in raw
    ][:MAX_COMMITS]
    return ComponentStatus(running=running, behind_by=behind, commits=commits)


async def check(now: datetime | None = None, transport: httpx.AsyncBaseTransport | None = None) -> CheckResult:
    """Asks GitHub what's newest, records the answer, and returns it."""
    now = now or datetime.now(timezone.utc)
    s = settings()
    result = CheckResult(checked_at=now.isoformat(), channel=s.update_channel)
    try:
        async with httpx.AsyncClient(timeout=15, headers=_headers(), transport=transport) as c:
            result.latest = await _latest(c, s.update_repo, s.update_channel)
            result.console = await _compare(c, s.update_repo, s.revision or None, result.latest.revision)
            result.flink = await _compare(c, s.update_repo, s.flink_revision or None,
                                          result.latest.revision, only_paths=FLINK_PATHS)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        result.error = (
            f"GitHub answered {code}. A private repository needs a read-only token "
            f"(MARS_UPDATE_TOKEN_SECRET)." if code in (401, 403, 404)
            else f"GitHub answered {code}."
        )
    except Exception as exc:  # network down, DNS, a bad token secret: say so, keep running
        result.error = str(exc)[:300] or exc.__class__.__name__
    try:
        result_path().write_text(json.dumps(asdict(result), indent=2))
    except OSError:
        log.exception("Could not record the update check")
    if result.error:
        log.warning("Update check failed: %s", result.error)
    return result
