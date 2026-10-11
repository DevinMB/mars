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
