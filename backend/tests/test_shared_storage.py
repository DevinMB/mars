"""Shared savepoint storage: the two-way check, and the generated override file."""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
import yaml

from app import settings as settings_mod
from app import shared_storage
from app.cluster_setup import savepoint_override
from app.gateway import GatewayError, StatementResult


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    settings_mod.settings.cache_clear()
    monkeypatch.setenv("MARS_DATA_DIR", str(tmp_path))
    yield tmp_path
    settings_mod.settings.cache_clear()


class _Gateway:
    """Runs the check's statements against a dict standing in for a disk."""

    def __init__(self, disk, fail_write=None, fail_read=None):
        self.disk, self.fail_write, self.fail_read = disk, fail_write, fail_read
        self.path = None

    async def open_session(self, props=None):
        return "s"

    async def close_session(self, session):
        pass

    async def execute(self, session, statement):
        if statement.startswith("CREATE"):
            self.path = re.search(r"'path' = '([^']+)'", statement).group(1)
        elif statement.startswith("INSERT"):
            if self.fail_write:
                raise self.fail_write
            self.disk[self.path] = [re.search(r"VALUES \('(\w+)'\)", statement).group(1)]
        return StatementResult(operation_handle="h", statement=statement)

    async def select_rows(self, session, statement, limit, budget=45.0):
        if self.fail_read:
            raise self.fail_read
        return StatementResult(operation_handle="h", statement=statement,
                               rows=[[t] for t in self.disk.get(self.path, [])])


class _Registry:
    def __init__(self, dirs, gateways):
        self.dirs, self.gateways = dirs, gateways

    def cluster(self, target):
        directory = self.dirs[target.name]

        async def config():
            return {"state.savepoints.dir": directory} if directory else {}
        return SimpleNamespace(config=config)

    def gateway(self, target, timeout=90.0):
        return self.gateways[target.name]


A, B = SimpleNamespace(name="default"), SimpleNamespace(name="mars-b")
SAME = {"default": "file:///flink-savepoints", "mars-b": "file:///flink-savepoints"}


@pytest.mark.asyncio
async def test_one_disk_seen_from_both_is_shared_and_remembered():
    disk = {}
    reg = _Registry(SAME, {"default": _Gateway(disk), "mars-b": _Gateway(disk)})
    out = await shared_storage.check(reg, A, B)
    assert out.shared, out.summary
    assert disk == {"file:///flink-savepoints/mars-storage-check": disk["file:///flink-savepoints/mars-storage-check"]}
    assert [c.shared for c in shared_storage.recorded()] == [True]


@pytest.mark.asyncio
async def test_the_same_path_on_two_disks_is_not_shared():
    # The default setup: both say file:///flink-state/savepoints, on separate machines.
    reg = _Registry(SAME, {"default": _Gateway({}), "mars-b": _Gateway({})})
    out = await shared_storage.check(reg, A, B)
    assert not out.shared
    assert "different disk" in out.summary


@pytest.mark.asyncio
async def test_different_locations_fail_without_running_anything():
    reg = _Registry({"default": "file:///a", "mars-b": "s3://b"}, {})
    out = await shared_storage.check(reg, A, B)
    assert not out.shared and "file:///a" in out.summary and "s3://b" in out.summary


@pytest.mark.asyncio
async def test_a_cluster_with_no_savepoint_directory_says_so():
    reg = _Registry({"default": "file:///a", "mars-b": None}, {})
    out = await shared_storage.check(reg, A, B)
    assert not out.shared and out.summary.startswith("mars-b: No savepoint directory")


@pytest.mark.asyncio
async def test_failures_name_the_cluster_and_the_likely_cause():
    disk = {}
    reg = _Registry(SAME, {"default": _Gateway(disk, fail_write=GatewayError("Permission denied")),
                           "mars-b": _Gateway(disk)})
    out = await shared_storage.check(reg, A, B)
    assert out.summary == "default could not write to file:///flink-savepoints: Permission denied"

    reg = _Registry(SAME, {"default": _Gateway(disk),
                           "mars-b": _Gateway(disk, fail_read=GatewayError("Statement did not settle within 60s"))})
    out = await shared_storage.check(reg, A, B)
    assert "mars-b could not read" in out.summary and "free task slot" in out.summary


def test_the_override_mounts_the_share_and_sets_the_location_on_the_command_line():
    text = savepoint_override("192.168.10.10", "/volume/x/.data")
    doc = yaml.safe_load(text)
    jm, tm = doc["services"]["jobmanager"], doc["services"]["taskmanager"]
    # -D and its value are separate words, or Flink takes the value as a host name.
    assert jm["command"] == ["jobmanager", "-D", "state.savepoints.dir=file:///flink-savepoints"]
    assert jm["volumes"] == tm["volumes"] == ["flink-savepoints:/flink-savepoints"]
    opts = doc["volumes"]["flink-savepoints"]["driver_opts"]
    assert opts == {"type": "nfs", "device": ":/volume/x/.data",
                    "o": "addr=192.168.10.10,nfsvers=3,nolock,rw,hard,timeo=600"}
    assert "docker compose up -d jobmanager taskmanager" in text


def test_the_override_can_cover_both_clusters_on_one_machine():
    doc = yaml.safe_load(savepoint_override("nas", "/x", [("jobmanager", "taskmanager"),
                                                          ("jobmanager-b", "taskmanager-b")]))
    assert set(doc["services"]) == {"jobmanager", "taskmanager", "jobmanager-b", "taskmanager-b"}


@pytest.mark.parametrize("server,export", [("nas;rm -rf /", "/x"), ("nas", "relative/path"),
                                           ("nas", "/x'\ny: 1"), ("", "/x")])
def test_the_override_refuses_values_that_would_break_the_file(server, export):
    with pytest.raises(ValueError):
        savepoint_override(server, export)


# -- job moves: off, ready, broken ---------------------------------------------

from app.models import Job, JobRun, RunState  # noqa: E402
from app.shared_storage import StorageCheck, depends_on_shared, job_moves  # noqa: E402

SHARED = "file:///flink-savepoints"


def _rec(shared, last=None, where=SHARED):
    return StorageCheck(clusters=["default", "mars-b"], shared=shared, summary="s", checked_at="t",
                        last_shared_at=last, shared_dir=where if last else None)


def test_never_set_up_is_off_not_an_error():
    dirs = {"default": "file:///flink-state/savepoints", "mars-b": "file:///flink-state/savepoints"}
    assert job_moves("default", "mars-b", dirs, []).state == "off"
    # A check that never passed is still just "not set up".
    assert job_moves("default", "mars-b", dirs, [_rec(False)]).state == "off"


def test_ready_while_both_still_save_to_the_shared_place():
    dirs = {"default": SHARED, "mars-b": SHARED}
    assert job_moves("default", "mars-b", dirs, [_rec(True, last="t")]).state == "ready"


def test_broken_when_it_worked_and_a_cluster_moved_away():
    dirs = {"default": SHARED, "mars-b": "file:///flink-state/savepoints"}
    m = job_moves("default", "mars-b", dirs, [_rec(True, last="t")])
    assert m.state == "broken" and m.summary.startswith("mars-b now saves to file:///flink-state/savepoints")


def test_broken_when_a_later_check_fails():
    dirs = {"default": SHARED, "mars-b": SHARED}
    assert job_moves("default", "mars-b", dirs, [_rec(False, last="earlier")]).state == "broken"


@pytest.mark.asyncio
async def test_a_failing_check_keeps_when_it_last_passed():
    disk = {}
    reg = _Registry(SAME, {"default": _Gateway(disk), "mars-b": _Gateway(disk)})
    passed = await shared_storage.check(reg, A, B)
    reg = _Registry(SAME, {"default": _Gateway({}), "mars-b": _Gateway({})})
    await shared_storage.check(reg, A, B)
    rec = shared_storage.recorded()[0]
    assert not rec.shared and rec.last_shared_at == passed.checked_at
    shared_storage.forget(["mars-b", "default"])
    assert shared_storage.recorded() == []


def test_jobs_resuming_from_the_share_block_turning_it_off(db):
    on_share = Job(name="sessions", sql_text="s", catalog_refs="[]")
    local = Job(name="lights", sql_text="s", catalog_refs="[]")
    db.add_all([on_share, local])
    db.flush()
    db.add(JobRun(job_id=on_share.id, job_version=1, state=RunState.CANCELED.value,
                  savepoint_path="file:/flink-savepoints/savepoint-1"))
    db.add(JobRun(job_id=local.id, job_version=1, state=RunState.RUNNING.value,
                  checkpoint_path="file:/flink-state/checkpoints/x/chk-3"))
    db.commit()
    assert depends_on_shared([on_share, local], SHARED) == ["sessions"]


# -- listing an NFS server's shares ------------------------------------------------

import struct  # noqa: E402

from app.nfs import Export, parse_exports  # noqa: E402


def _xdr_string(s):
    b = s.encode()
    return struct.pack(">I", len(b)) + b + b"\0" * ((4 - len(b) % 4) % 4)


def test_exports_are_read_from_the_mount_reply():
    body = (struct.pack(">I", 1) + _xdr_string("/volume/u/.srv/.unifi-drive/mars.savepoints/.data")
            + struct.pack(">I", 1) + _xdr_string("192.168.10.13")
            + struct.pack(">I", 1) + _xdr_string("192.168.1.250") + struct.pack(">I", 0)
            + struct.pack(">I", 1) + _xdr_string("/srv/nfs/open") + struct.pack(">I", 0)
            + struct.pack(">I", 0))
    found = parse_exports(body)
    assert [(e.name, e.clients) for e in found] == [
        ("mars.savepoints", ["192.168.10.13", "192.168.1.250"]), ("open", [])]


def test_a_reply_cut_short_is_an_error_not_a_crash():
    from app.nfs import NfsError
    with pytest.raises(NfsError):
        parse_exports(struct.pack(">I", 1) + struct.pack(">I", 40) + b"short")


def test_share_names_skip_hidden_parts():
    assert Export("/volume1/flink-savepoints", []).name == "flink-savepoints"
    assert Export("/volume/x/.srv/.unifi-drive/a.b/.data", []).name == "a.b"
