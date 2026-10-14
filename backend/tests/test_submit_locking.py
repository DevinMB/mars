"""Starting a job must not hold SQLite's write lock while it waits on Flink.

It used to: the new run was flushed, not committed, before the calls to the SQL
Gateway. The scheduler's next write then waited for the lock, and that wait is a
blocking call on the event loop, so the whole console froze for the full lock
timeout (30 seconds) -- the submission included, since it needed the same loop
to finish. Seen in production as a UI that hung while a job resumed.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.gateway import StatementResult
from app.models import Job, JobRun, RunState, Schedule, utcnow
from app.submitter import JobSubmitter, SubmissionError


@pytest.fixture
def sessions(tmp_path):
    # A real file with WAL, as in production; an in-memory database shares one
    # connection and cannot show lock contention.
    engine = create_engine(f"sqlite:///{tmp_path / 'mars.db'}",
                           connect_args={"check_same_thread": False, "timeout": 1})

    @event.listens_for(engine, "connect")
    def _wal(conn, _):
        conn.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


class _Gateway:
    """Holds the submission at the first gateway call until released."""

    def __init__(self, fail=None):
        self.entered, self.release, self.fail = asyncio.Event(), asyncio.Event(), fail

    async def open_session(self, props=None):
        self.entered.set()
        await self.release.wait()
        if self.fail:
            raise self.fail
        return "s"

    async def close_session(self, session):
        pass

    async def execute(self, session, statement):
        return StatementResult(operation_handle="h", statement=statement)

    async def execute_script(self, session, statements):
        return [StatementResult(operation_handle="h", statement=s, job_id="f" * 32) for s in statements]


def _submitter(gateway):
    cluster = SimpleNamespace(list_jobs=_no_jobs)
    store = SimpleNamespace(resolve=lambda db, s: s, redact=lambda db, s: s)
    return JobSubmitter(gateway, cluster, store)


async def _no_jobs():
    return []


def _job(Session):
    with Session() as db:
        job = Job(name="sessions", sql_text="INSERT INTO out SELECT 1", catalog_refs="[]")
        db.add(job)
        db.commit()
        return job.id


@pytest.mark.asyncio
async def test_other_writers_are_not_blocked_while_a_job_starts(sessions):
    job_id = _job(sessions)
    gateway = _Gateway()
    db = sessions()
    task = asyncio.create_task(_submitter(gateway)._submit(db, db.get(Job, job_id), "devin", False, None))
    await gateway.entered.wait()

    # What the scheduler does meanwhile: a write of its own. Before the fix this
    # raised "database is locked" after the timeout.
    with sessions() as other:
        other.add(Schedule(job_id=job_id, mode="supervisor", enabled=True))
        other.commit()
        # The run is already visible, so a second Run sees the job as busy.
        assert other.query(JobRun).one().state == RunState.SUBMITTING.value

    gateway.release.set()
    run = await task
    assert run.state == RunState.RUNNING.value and run.flink_job_id == "f" * 32
    db.close()


@pytest.mark.asyncio
async def test_an_unexpected_error_fails_the_run_instead_of_leaving_it_submitting(sessions):
    job_id = _job(sessions)
    gateway = _Gateway(fail=ConnectionError("gateway unreachable"))
    gateway.release.set()
    db = sessions()
    with pytest.raises(SubmissionError, match="gateway unreachable"):
        await _submitter(gateway)._submit(db, db.get(Job, job_id), "devin", False, None)
    db.close()
    with sessions() as check:
        run = check.query(JobRun).one()
        assert run.state == RunState.FAILED.value and "gateway unreachable" in run.error_summary


def test_a_submission_that_never_finished_is_failed_after_a_while(sessions):
    job_id = _job(sessions)
    with sessions() as db:
        db.add(JobRun(job_id=job_id, job_version=1, state=RunState.SUBMITTING.value,
                      started_at=utcnow() - timedelta(minutes=30)))
        db.add(JobRun(job_id=job_id, job_version=1, state=RunState.SUBMITTING.value,
                      started_at=utcnow()))
        db.commit()
        assert JobSubmitter.expire_stale_submissions(db) == 1
        states = sorted(r.state for r in db.query(JobRun))
        assert states == [RunState.FAILED.value, RunState.SUBMITTING.value]
