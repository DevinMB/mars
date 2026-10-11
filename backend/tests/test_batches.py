"""Bulk job actions run by the console: order, halting, stopping, restarts."""
from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import batches, moves
from app.db import Base
from app.models import BatchOperation, Job, JobRun, RunState, utcnow
from app.submitter import SubmissionError

DEFAULT = SimpleNamespace(name="default", is_default=True)
B = SimpleNamespace(name="mars-b", is_default=False)


@pytest.fixture
def Session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'mars.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @contextmanager
    def scope():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(batches, "session_scope", scope)
    yield factory
    engine.dispose()


class _Submitter:
    def __init__(self, log, fail=()):
        self.log, self.fail = log, set(fail)

    async def submit(self, db, job, submitted_by=None, savepoint_path=None):
        self.log.append(("start", job.name, job.target_name))
        db.add(JobRun(job_id=job.id, job_version=1, state=RunState.RUNNING.value))
        db.commit()

    async def stop_with_savepoint(self, db, run, native=False):
        job = db.get(Job, run.job_id)
        if job.name in self.fail:
            raise SubmissionError("Could not save this job's state, so it has been left running.")
        self.log.append(("stop", job.name))
        run.state, run.savepoint_path, run.ended_at = RunState.CANCELED.value, "file:///sp/x", utcnow()
        db.commit()


class _Registry:
    def __init__(self, log, fail_stop=()):
        self.sub = _Submitter(log, fail_stop)

    def all_enabled(self, db):
        return [DEFAULT, B]

    def for_job(self, db, job):
        return B if job.target_name == "mars-b" else DEFAULT

    def for_job_submitter(self, db, job):
        return self.sub


@pytest.fixture
def fake_move(monkeypatch):
    log, fail = [], set()

    async def move(db, registry, job, dest, user, native=False):
        if job.name in fail:
            raise moves.MoveError("mars-b has no free task slot.")
        log.append(("move", job.name, dest))
        job.target_name = None if dest == "default" else dest
        db.commit()
        return moves.MoveResult(True, f"{job.name} now runs on {dest}.")

    monkeypatch.setattr(moves, "move", move)
    return SimpleNamespace(log=log, fail=fail)


def _jobs(Session, *names, running=True, target=None):
    with Session() as db:
        for n in names:
            job = Job(name=n, sql_text="s", catalog_refs="[]", target_name=target)
            db.add(job)
            db.flush()
            db.add(JobRun(job_id=job.id, job_version=1,
                          state=RunState.RUNNING.value if running else RunState.CANCELED.value))
        db.commit()


def _start(Session, registry, kind, names, cluster=None):
    with Session() as db:
        return batches.create(db, registry, kind, names, cluster, "devin").id


def _result(Session, batch_id):
    with Session() as db:
        b = db.get(BatchOperation, batch_id)
        return b.status, [(i["job"], i["status"]) for i in batches.items_of(b)]


@pytest.mark.asyncio
async def test_a_move_batch_moves_each_job_in_turn(Session, fake_move):
    _jobs(Session, "a", "b")
    reg = _Registry([])
    bid = _start(Session, reg, "move", ["a", "b"], "mars-b")
    await batches.run(bid, reg)
    assert fake_move.log == [("move", "a", "mars-b"), ("move", "b", "mars-b")]
    assert _result(Session, bid) == ("done", [("a", "done"), ("b", "done")])


@pytest.mark.asyncio
async def test_a_move_batch_halts_at_the_first_failure(Session, fake_move):
    _jobs(Session, "a", "b", "c")
    fake_move.fail.add("b")
    reg = _Registry([])
    bid = _start(Session, reg, "move", ["a", "b", "c"], "mars-b")
    await batches.run(bid, reg)
    assert _result(Session, bid) == ("failed", [("a", "done"), ("b", "failed"), ("c", "notrun")])


@pytest.mark.asyncio
async def test_stops_carry_on_past_a_failure_and_skip_what_is_not_running(Session):
    _jobs(Session, "a", "b")
    _jobs(Session, "idle", running=False)
    log = []
    reg = _Registry(log, fail_stop={"a"})
    bid = _start(Session, reg, "stop", ["a", "idle", "b"])
    await batches.run(bid, reg)
    assert _result(Session, bid) == ("done", [("a", "failed"), ("idle", "skipped"), ("b", "done")])
    assert log == [("stop", "b")]


@pytest.mark.asyncio
async def test_a_batch_interrupted_mid_move_finishes_it_after_a_restart(Session, fake_move):
    # The console stopped after re-pointing "a" at mars-b but before starting it.
    _jobs(Session, "a", running=False, target="mars-b")
    _jobs(Session, "b")
    with Session() as db:
        db.add(BatchOperation(kind="move", cluster="mars-b", status="running", created_by="devin",
                              items=json.dumps([
                                  {"job": "a", "was_running": True, "status": "working", "note": ""},
                                  {"job": "b", "was_running": True, "status": "waiting", "note": ""}])))
        db.commit()
        bid = db.query(BatchOperation).one().id
    log = []
    reg = _Registry(log)
    await batches.run(bid, reg)
    assert ("start", "a", "mars-b") in log  # resumed where it was being moved to
    assert fake_move.log == [("move", "b", "mars-b")]
    assert _result(Session, bid) == ("done", [("a", "done"), ("b", "done")])


@pytest.mark.asyncio
async def test_only_one_batch_at_a_time_and_stopping_leaves_the_rest(Session, fake_move):
    _jobs(Session, "a", "b")
    reg = _Registry([])
    bid = _start(Session, reg, "move", ["a", "b"], "mars-b")
    with Session() as db:
        with pytest.raises(batches.BatchError, match="still running"):
            batches.create(db, reg, "stop", ["a"], None, "devin")
        batches.request_stop(db, db.get(BatchOperation, bid))
    await batches.run(bid, reg)
    assert _result(Session, bid) == ("stopped", [("a", "notrun"), ("b", "notrun")])
    assert fake_move.log == []


def test_a_move_needs_a_known_cluster(Session):
    _jobs(Session, "a")
    with Session() as db, pytest.raises(batches.BatchError, match="Choose a cluster"):
        batches.create(db, _Registry([]), "move", ["a"], "nowhere", "devin")
