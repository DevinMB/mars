"""The restore drill: passes on a good backup, and fails on each way a backup goes bad.

A drill that always passes proves nothing, so most of these build a broken backup
and check the drill says so, and says why.
"""
from __future__ import annotations

import io
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.script import ScriptDirectory
from cryptography.fernet import Fernet
from prometheus_client import REGISTRY
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app import metrics, restore_drill
from app.db import Base
from app.migrations import _config
from app.models import CatalogEntry, Job, Secret, User

NOW = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)
HEAD = ScriptDirectory.from_config(_config()).get_current_head()


def make_install(root: Path, jobs=("a", "b"), key: bytes | None = None) -> Path:
    data = root / "data"
    data.mkdir(parents=True)
    key = key or Fernet.generate_key()
    (data / "secret.key").write_bytes(key)
    engine = create_engine(f"sqlite:///{data / 'mars.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.execute(text("create table alembic_version (version_num varchar(32) not null)"))
        db.execute(text("insert into alembic_version values (:v)"), {"v": HEAD})
        for name in jobs:
            db.add(Job(name=name, sql_text="s", catalog_refs="[]"))
        db.add(CatalogEntry(name="src", kind="source", connector="kafka", sql_text="s"))
        db.add(User(username="operator", password_hash="x", role="admin"))
        db.add(Secret(name="couch_pw", ciphertext=Fernet(key).encrypt(b"hunter2").decode()))
        db.commit()
    engine.dispose()
    return data


def archive(data: Path, out: Path, skip: tuple[str, ...] = ()) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w:gz") as tar:
        for f in ("mars.db", "secret.key"):
            if f not in skip:
                tar.add(data / f, arcname=f)
    return out


@pytest.fixture
def install(tmp_path, monkeypatch):
    data = make_install(tmp_path / "live")
    backups = tmp_path / "backups"
    backups.mkdir()
    state = tmp_path / "flink-state"
    cfg = SimpleNamespace(
        data_dir=data, secret_key_file="secret.key", restore_drill=True,
        restore_drill_schedule="0 6 1 1,4,7,10 *", restore_drill_backups_dir=str(backups),
        flink_state_dir=str(state),
    )
    monkeypatch.setattr(restore_drill, "settings", lambda: cfg)
    monkeypatch.setattr(metrics, "settings", lambda: cfg)
    monkeypatch.setattr(restore_drill, "_restore_point_paths", lambda: [])
    return SimpleNamespace(data=data, backups=backups, state=state, cfg=cfg, root=tmp_path)


def failed(result) -> dict[str, str]:
    return {c.name: c.detail for c in result.checks if not c.ok}


def test_snapshot_of_live_passes_when_there_are_no_archives(install):
    result = restore_drill.run(now=NOW)
    assert result.passed, failed(result)
    assert result.source == "snapshot of the live database"


def test_newest_archive_passes(install):
    archive(install.data, install.backups / "console-data-1.tgz")
    result = restore_drill.run(now=NOW)
    assert result.passed, failed(result)
    assert result.source == "archive console-data-1.tgz"


def test_result_is_recorded_for_metrics(install):
    restore_drill.run(now=NOW)
    last = restore_drill.last_result()
    assert last.passed and last.ran_at == NOW.isoformat()


def test_archive_without_its_key_fails(install):
    archive(install.data, install.backups / "no-key.tgz", skip=("secret.key",))
    result = restore_drill.run(now=NOW)
    assert not result.passed
    assert "backup holds the database and its key" in failed(result)


def test_archive_with_the_wrong_key_fails_on_secrets(install):
    other = make_install(install.root / "other", key=Fernet.generate_key())
    with tarfile.open(install.backups / "wrong-key.tgz", "w:gz") as tar:
        tar.add(install.data / "mars.db", arcname="mars.db")
        tar.add(other / "secret.key", arcname="secret.key")
    result = restore_drill.run(now=NOW)
    assert failed(result).get("every secret decrypts with the backed-up key", "").startswith("0/1")


def test_stale_archive_missing_a_job_fails(install):
    stale = make_install(install.root / "stale", jobs=("a",),
                         key=(install.data / "secret.key").read_bytes())
    archive(stale, install.backups / "stale.tgz")
    result = restore_drill.run(now=NOW)
    assert "same jobs as live" in failed(result)


def test_unreadable_archive_fails(install):
    (install.backups / "garbage.tgz").write_bytes(b"not a tarball")
    result = restore_drill.run(now=NOW)
    assert "backup can be read" in failed(result)


def test_archive_cannot_write_outside_its_directory(install):
    buf = io.BytesIO(b"x")
    with tarfile.open(install.backups / "escape.tgz", "w:gz") as tar:
        info = tarfile.TarInfo("../../escaped")
        info.size = 1
        tar.addfile(info, buf)
    result = restore_drill.run(now=NOW)
    assert "backup can be read" in failed(result)
    assert not (install.root / "escaped").exists()


def test_missing_restore_point_fails(install, monkeypatch):
    (install.state / "savepoints" / "sp-1").mkdir(parents=True)
    (install.state / "savepoints" / "sp-1" / "_metadata").write_bytes(b"m")
    monkeypatch.setattr(restore_drill, "_restore_point_paths", lambda: [
        ("a", "file:/flink-state/savepoints/sp-1"),
        ("b", "file:/flink-state/checkpoints/x/chk-9"),
    ])
    result = restore_drill.run(now=NOW)
    assert failed(result)["every running job's restore point is on disk"] == "1/2; missing: b"


def test_restore_points_are_skipped_when_state_is_not_mounted(install):
    result = restore_drill.run(now=NOW)
    check = next(c for c in result.checks if c.name.startswith("every running job"))
    assert check.ok and check.detail.startswith("skipped")


def test_schedule(install):
    assert restore_drill.is_due(NOW), "never run: due"
    restore_drill.run(now=NOW)
    assert not restore_drill.is_due(NOW + timedelta(days=30))
    assert restore_drill.is_due(datetime(2027, 1, 1, 6, 0, tzinfo=timezone.utc))
    install.cfg.restore_drill = False
    assert not restore_drill.is_due(datetime(2030, 1, 1, tzinfo=timezone.utc))


def sample(name: str, source: str):
    return REGISTRY.get_sample_value(name, {"source": source})


def test_metrics_are_absent_while_the_drill_is_off(install, db):
    restore_drill.run(now=NOW)
    install.cfg.restore_drill = False
    metrics.refresh(db, now=NOW)
    assert sample("mars_restore_drill_success", "snapshot of the live database") is None


def test_metrics_report_a_failure(install, db):
    archive(install.data, install.backups / "no-key.tgz", skip=("secret.key",))
    restore_drill.run(now=NOW)
    metrics.refresh(db, now=NOW)
    assert sample("mars_restore_drill_success", "archive no-key.tgz") == 0
    assert sample("mars_restore_drill_last_run_timestamp_seconds", "archive no-key.tgz") == NOW.timestamp()
