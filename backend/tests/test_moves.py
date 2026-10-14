"""Moving a job between clusters: checked first, undone if the start fails."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import moves
from app.models import Job, JobRun, RunState, utcnow
from app.submitter import SubmissionError

SHARED = "file:///flink-savepoints"
DEFAULT = SimpleNamespace(name="default", is_default=True)
B = SimpleNamespace(name="mars-b", is_default=False)


class _Submitter:
    def __init__(self, name, log, fail_submit=None, savepoint=f"{SHARED}/savepoint-1"):
        self.name, self.log, self.fail_submit, self.savepoint = name, log, fail_submit, savepoint

    async def stop_with_savepoint(self, db, run, native=False):
        self.native = native
        self.log.append(("stop", self.name))
        run.savepoint_path, run.state, run.ended_at = self.savepoint, RunState.CANCELED.value, utcnow()
        db.commit()
        return self.savepoint

    async def submit(self, db, job, submitted_by=None, savepoint_path=None):
        self.log.append(("start", self.name, job.target_name, savepoint_path))
        run = JobRun(job_id=job.id, job_version=1, state=RunState.FAILED.value if self.fail_submit
                     else RunState.RUNNING.value, restored_from=savepoint_path)
        db.add(run)
        db.commit()
        if self.fail_submit:
            raise SubmissionError(self.fail_submit)
        return run


class _Registry:
    def __init__(self, log, slots=4, versions=("2.2.1", "2.2.1"), fail_on=None):
        self.log = log
        self.subs = {"default": _Submitter("default", log),
                     "mars-b": _Submitter("mars-b", log, fail_submit="slot request timed out" if fail_on == "mars-b" else None)}
        self.slots, self.versions = slots, dict(zip(("default", "mars-b"), versions))

    def all_enabled(self, db):
        return [DEFAULT, B]

    def for_job(self, db, job):
        return B if job.target_name == "mars-b" else DEFAULT

    def submitter(self, target):
        return self.subs[target.name]

    def cluster(self, target):
        async def info():
            return SimpleNamespace(slots_available=self.slots, flink_version=self.versions[target.name])
        return SimpleNamespace(info=info)


@pytest.fixture(autouse=True)
def shared(monkeypatch):
    async def ready(registry, db, a, b):
        return SHARED, ""
    monkeypatch.setattr(moves, "_shared_dir", ready)


def _running(db, target=None):
    job = Job(name="lights", sql_text="s", catalog_refs="[]", target_name=target)
    db.add(job)
    db.flush()
    db.add(JobRun(job_id=job.id, job_version=1, state=RunState.RUNNING.value, flink_job_id="a" * 32))
    db.commit()
    return job


@pytest.mark.asyncio
async def test_a_running_job_is_stopped_here_and_resumed_there_from_that_savepoint(db):
    log = []
    job = _running(db)
    result = await moves.move(db, _Registry(log), job, "mars-b", "devin")
    assert result.moved and result.savepoint == f"{SHARED}/savepoint-1"
    assert log == [("stop", "default"), ("start", "mars-b", "mars-b", f"{SHARED}/savepoint-1")]
    assert job.target_name == "mars-b"


@pytest.mark.asyncio
async def test_moving_back_to_the_default_clears_the_target(db):
    log = []
    job = _running(db, target="mars-b")
    await moves.move(db, _Registry(log), job, "default", "devin")
    assert job.target_name is None and log[0] == ("stop", "mars-b")


@pytest.mark.asyncio
async def test_a_failed_start_puts_it_back_where_it_was(db):
    log = []
    job = _running(db)
    with pytest.raises(moves.MoveError, match="running on default again"):
        await moves.move(db, _Registry(log, fail_on="mars-b"), job, "mars-b", "devin")
    assert job.target_name is None
    # Resumed on the original cluster, from the savepoint the move took.
    assert log[-1] == ("start", "default", None, f"{SHARED}/savepoint-1")
    db.expire(job)
    assert [r.state for r in job.runs][:2] == [RunState.RUNNING.value, RunState.FAILED.value]


@pytest.mark.asyncio
async def test_nothing_is_stopped_when_the_destination_cannot_take_it(db):
    log = []
    job = _running(db)
    with pytest.raises(moves.MoveError, match="no free task slot"):
        await moves.move(db, _Registry(log, slots=0), job, "mars-b", "devin")
    # Flink cannot restore onto an older version.
    with pytest.raises(moves.MoveError, match="older than 2.3.0 here"):
        await moves.move(db, _Registry(log, versions=("2.3.0", "2.2.1")), job, "mars-b", "devin")
    assert log == [] and job.target_name is None


@pytest.mark.asyncio
async def test_moving_onto_a_newer_flink_is_allowed_and_said(db):
    job = _running(db)
    opts = await moves.options(db, _Registry([], versions=("2.2.1", "2.3.0")), job)
    assert opts[0].ok and "cannot move back to default" in opts[0].notes[0]


@pytest.mark.asyncio
async def test_a_stopped_job_moves_only_if_its_state_is_on_the_share(db):
    job = Job(name="lights", sql_text="s", catalog_refs="[]")
    db.add(job)
    db.flush()
    db.add(JobRun(job_id=job.id, job_version=1, state=RunState.CANCELED.value,
                  savepoint_path="file:/flink-state/savepoints/savepoint-0", ended_at=utcnow()))
    db.commit()
    log = []
    with pytest.raises(moves.MoveError, match="own disk"):
        await moves.move(db, _Registry(log), job, "mars-b", "devin")

    db.add(JobRun(job_id=job.id, job_version=1, state=RunState.CANCELED.value,
                  savepoint_path="file:/flink-savepoints/savepoint-2", ended_at=utcnow()))
    db.commit()
    db.expire(job)
    result = await moves.move(db, _Registry(log), job, "mars-b", "devin")
    assert result.moved and job.target_name == "mars-b" and log == []  # nothing started


@pytest.mark.asyncio
async def test_options_say_why_not(db):
    job = _running(db)
    opts = await moves.options(db, _Registry([], slots=0), job)
    assert [(o.cluster, o.ok) for o in opts] == [("mars-b", False)]
    assert "no free task slot" in opts[0].reasons[0]
