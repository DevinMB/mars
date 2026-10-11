"""Whether two clusters share savepoint storage, proven rather than guessed.

Moving a job between clusters means stopping it with a savepoint on one and
resuming it from that path on the other, so the second cluster must read the
first one's files at the same path. Comparing the configured directories is not
enough: two clusters on separate machines both saying file:///flink-state/...
are two different disks. That is exactly what the default setup looks like.

So the check has each cluster write a random token into the savepoint directory
with a small batch job, and the other read it back, in both directions. It runs
as Flink's own user, on the storage Flink itself uses -- local disk, a shared
mount or object storage -- and the console touches no files. Each direction
briefly needs one free task slot per cluster. A ``mars-storage-check`` folder
of a few bytes is left in the savepoint directory; it is not a savepoint, and
retention ignores it.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .gateway import GatewayError
from .models import Target
from .settings import settings

# Flink 2 names the option the first way and still accepts the second.
SAVEPOINT_KEYS = ("execution.checkpointing.savepoint-dir", "state.savepoints.dir")
# Not hidden: Flink's file source skips paths starting with "." or "_", so a
# hidden folder would always read back empty and every check would fail.
PROBE_DIR = "mars-storage-check"
_BATCH = {"execution.runtime-mode": "batch", "parallelism.default": "1"}


@dataclass
class StorageCheck:
    clusters: list[str]
    shared: bool
    summary: str
    checked_at: str
    detail: str | None = None


def savepoint_dir(config: dict[str, str]) -> str | None:
    for key in SAVEPOINT_KEYS:
        if config.get(key):
            return config[key]
    return None


async def location(registry, target: Target) -> tuple[str | None, str | None]:
    """(savepoint directory, error) as the cluster reports it."""
    try:
        directory = savepoint_dir(await registry.cluster(target).config())
    except Exception as exc:  # unreachable, or not a Flink REST endpoint
        return None, f"Could not ask the cluster: {exc}"
    if not directory:
        return None, "No savepoint directory is configured, so jobs cannot be stopped with their state."
    return directory, None


def _table(directory: str) -> str:
    path = f"{directory.rstrip('/')}/{PROBE_DIR}".replace("'", "''")
    return (
        "CREATE TEMPORARY TABLE mars_storage_check (token STRING) "
        f"WITH ('connector' = 'filesystem', 'path' = '{path}', 'format' = 'csv')"
    )


async def _write(gateway, directory: str, token: str) -> None:
    session = await gateway.open_session({**_BATCH, "table.dml-sync": "true"})
    try:
        await gateway.execute(session, _table(directory))
        await gateway.execute(session, f"INSERT OVERWRITE mars_storage_check VALUES ('{token}')")
    finally:
        await gateway.close_session(session)


async def _read(gateway, directory: str) -> list[str]:
    session = await gateway.open_session(_BATCH)
    try:
        await gateway.execute(session, _table(directory))
        result = await gateway.select_rows(session, "SELECT token FROM mars_storage_check", 10, budget=60)
        return [str(row[0]) for row in result.rows if row]
    finally:
        await gateway.close_session(session)


def _reason(exc: Exception) -> str:
    text = exc.summary if isinstance(exc, GatewayError) else str(exc)
    if "did not settle" in text:
        return "it did not start a job in time; it may have no free task slot"
    return text


async def check(registry, a: Target, b: Target) -> StorageCheck:
    now = datetime.now(timezone.utc).isoformat()
    names = [a.name, b.name]

    def result(shared: bool, summary: str, detail: str | None = None) -> StorageCheck:
        out = StorageCheck(clusters=names, shared=shared, summary=summary, checked_at=now, detail=detail)
        _record(out)
        return out

    (dir_a, err_a), (dir_b, err_b) = await location(registry, a), await location(registry, b)
    if err_a or err_b:
        return result(False, f"{a.name if err_a else b.name}: {err_a or err_b}")
    if dir_a != dir_b:
        return result(False, f"{a.name} saves to {dir_a} and {b.name} to {dir_b}. A job moved "
                             f"between them would look for its savepoint in the wrong place, so "
                             f"both must use the same location.")

    for src, dst in ((a, b), (b, a)):
        token = secrets.token_hex(8)
        try:
            await _write(registry.gateway(src), dir_a, token)
        except Exception as exc:
            return result(False, f"{src.name} could not write to {dir_a}: {_reason(exc)}")
        try:
            seen = await _read(registry.gateway(dst), dir_a)
        except Exception as exc:
            return result(False, f"{dst.name} could not read {dir_a}: {_reason(exc)}")
        if token not in seen:
            return result(False, f"{dst.name} does not see what {src.name} wrote to {dir_a}. Both "
                                 f"name the same path, but it is a different disk on each.")
    return result(True, f"Both clusters read and write the same savepoint storage, {dir_a}. "
                        f"Jobs can move between them.")


# -- the last result for each pair, kept across restarts -------------------------

def _path() -> Path:
    return settings().data_dir / "storage-checks.json"


def _key(names: list[str]) -> str:
    return "|".join(sorted(names))


def _load() -> dict[str, dict]:
    try:
        raw = json.loads(_path().read_text())
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _record(check_: StorageCheck) -> None:
    data = _load()
    data[_key(check_.clusters)] = asdict(check_)
    try:
        _path().write_text(json.dumps(data, indent=2))
    except OSError:
        pass  # shown now, just not remembered


def recorded() -> list[StorageCheck]:
    return [StorageCheck(**v) for v in _load().values()]
