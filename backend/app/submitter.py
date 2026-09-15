"""Turns a stored job into a running Flink job.

The submission pipeline, in order:

1. Collect the catalog fragments the job declares, in dependency order.
2. Concatenate them with the job's own statement.
3. Resolve ``${secret:name}`` references -- the last possible moment, and the only
   point at which plaintext credentials exist.
4. Open a gateway session, replay the DDL, then execute the job statement.
5. Record the Flink job id against a JobRun.

Step 3 is why the resolved script is never stored, logged, or returned. Step 1 is
what makes ephemeral gateway sessions workable without a metastore.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from .cluster import FlinkClusterClient
from .ddl import split_statements
from .gateway import GatewayError, SqlGatewayClient
from .models import CatalogEntry, Job, JobRun, RunState, utcnow
from .secrets import SecretStore

log = logging.getLogger(__name__)


class SubmissionError(RuntimeError):
    def __init__(self, summary: str, detail: str = "") -> None:
        super().__init__(summary)
        self.summary = summary
        self.detail = detail


class JobSubmitter:
    def __init__(
        self,
        gateway: SqlGatewayClient,
        cluster: FlinkClusterClient,
        store: SecretStore,
    ) -> None:
        self._gateway = gateway
        self._cluster = cluster
        self._store = store

    def build_script(self, db: Session, job: Job) -> list[str]:
        """Assembles the statements for a job without resolving secrets.

        Safe to show a user: every credential is still a ``${secret:...}``
        placeholder. This is what the console's "preview SQL" renders.
        """
        refs = _catalog_refs(job)
        statements: list[str] = []

        if refs:
            entries = {
                e.name: e
                for e in db.query(CatalogEntry).filter(CatalogEntry.name.in_(refs)).all()
            }
            missing = [r for r in refs if r not in entries]
            if missing:
                raise SubmissionError(
                    f"Job '{job.name}' references unknown catalog entries: "
                    f"{', '.join(missing)}. They may have been renamed or deleted."
                )
            # Preserve the order the job declared, so a table that depends on
            # another is created after it.
            for ref in refs:
                statements.extend(split_statements(entries[ref].sql_text))

        statements.extend(split_statements(job.sql_text))
        if not statements:
            raise SubmissionError(f"Job '{job.name}' has no SQL to run.")
        return statements

    async def validate(self, db: Session, job: Job) -> None:
        """Compiles the job without submitting it."""
        statements = self.build_script(db, job)
        resolved = [self._store.resolve(db, s) for s in statements]

        session = await self._gateway.open_session()
        try:
            # Everything but the final statement is DDL that must actually run for
            # the last statement to resolve its tables.
            for stmt in resolved[:-1]:
                await self._gateway.execute(session, stmt)
            await self._gateway.validate(session, resolved[-1])
        except GatewayError as exc:
            raise SubmissionError(
                self._store.redact(db, exc.summary),
                detail=self._store.redact(db, exc.detail),
            ) from exc
        finally:
            await self._gateway.close_session(session)

    async def submit(
        self,
        db: Session,
        job: Job,
        submitted_by: str | None = None,
        by_schedule: bool = False,
    ) -> JobRun:
        statements = self.build_script(db, job)

        run = JobRun(
            job_id=job.id,
            job_version=job.version,
            state=RunState.SUBMITTING.value,
            submitted_by=submitted_by,
            triggered_by_schedule=by_schedule,
        )
        db.add(run)
        db.flush()

        try:
            resolved = [self._store.resolve(db, s) for s in statements]
        except Exception as exc:
            _fail(run, self._store.redact(db, str(exc)))
            db.commit()
            raise SubmissionError(str(exc)) from exc

        session = await self._gateway.open_session(
            {"pipeline.name": f"mars:{job.name}"}
        )
        try:
            results = await self._gateway.execute_script(session, resolved)
            job_id = next((r.job_id for r in reversed(results) if r.job_id), None)

            if job_id is None:
                # DDL-only scripts produce no job. That is a user error here: the
                # thing they pressed Run on did not start anything.
                _fail(
                    run,
                    "The job ran but started nothing. A job needs a statement that "
                    "produces output, such as INSERT INTO.",
                )
                db.commit()
                raise SubmissionError(run.error_summary or "No job was started")

            run.flink_job_id = job_id
            run.state = RunState.RUNNING.value
            db.commit()
            log.info("Submitted job '%s' as Flink job %s", job.name, job_id)
            return run

        except GatewayError as exc:
            summary = self._store.redact(db, exc.summary)
            detail = self._store.redact(db, exc.detail)
            _fail(run, summary, detail)
            db.commit()
            raise SubmissionError(summary, detail) from exc
        finally:
            await self._gateway.close_session(session)

    async def cancel(self, db: Session, run: JobRun) -> None:
        if run.flink_job_id:
            await self._cluster.cancel(run.flink_job_id)
        run.state = RunState.CANCELED.value
        run.ended_at = utcnow()
        db.commit()

    async def refresh_states(self, db: Session, target_name: str | None = ...) -> int:
        """Reconciles MARS's view of runs with what this cluster reports.

        Without this, a job that failed overnight still reads as running in the
        console, which is exactly the kind of quiet lie that makes an operator stop
        trusting a dashboard.

        ``target_name`` scopes the reconcile to jobs placed on one target. That
        matters once there is more than one cluster: asking the default cluster
        about a job running elsewhere gets "no such job", and the run would be
        marked lost while it is running perfectly well somewhere else. Passing the
        sentinel default reconciles everything, which is correct only in a
        single-cluster deployment.
        """
        query = (
            db.query(JobRun)
            .filter(
                JobRun.state.in_(
                    [
                        RunState.RUNNING.value,
                        RunState.SUBMITTING.value,
                        RunState.RESTARTING.value,
                    ]
                )
            )
            .filter(JobRun.flink_job_id.isnot(None))
        )
        if target_name is not ...:
            query = query.join(Job, JobRun.job_id == Job.id)
            if target_name is None:
                query = query.filter(Job.target_name.is_(None))
            else:
                query = query.filter(Job.target_name == target_name)
        active = query.all()
        if not active:
            return 0

        try:
            overviews = {o.job_id: o for o in await self._cluster.list_jobs()}
        except Exception as exc:
            log.warning("Could not reach Flink to refresh job states: %s", exc)
            return 0

        changed = 0
        for run in active:
            o = overviews.get(run.flink_job_id or "")
            if o is None:
                # The cluster has forgotten it -- a restart with no HA storage, or
                # history expiry. Do not claim it is still running.
                run.state = RunState.FAILED.value
                run.ended_at = run.ended_at or utcnow()
                run.error_summary = (
                    "Flink no longer knows about this job. It was most likely lost "
                    "when the cluster restarted."
                )
                changed += 1
                continue

            new_state = _map_state(o.state)

            if new_state == RunState.RESTARTING.value:
                # Count every poll that catches it restarting, and explain why as
                # soon as the cluster has an exception to give us.
                run.restarts += 1
                if not run.error_summary:
                    run.error_summary = await self._fetch_failure(db, run.flink_job_id)

            if new_state != run.state:
                run.state = new_state
                if new_state in (
                    RunState.FINISHED.value,
                    RunState.FAILED.value,
                    RunState.CANCELED.value,
                ):
                    run.ended_at = utcnow()
                    if new_state == RunState.FAILED.value and not run.error_summary:
                        summary, detail = await self._fetch_failure(
                            db, run.flink_job_id
                        )
                        run.error_summary = summary
                        # Keep the whole trace, not just the headline: the cause
                        # of a runtime failure is usually several frames down,
                        # and Flink drops the job from its history eventually.
                        if detail and not run.error_detail:
                            run.error_detail = detail
                changed += 1

        if changed:
            db.commit()
        return changed

    async def _fetch_failure(
        self, db: Session, flink_job_id: str | None
    ) -> tuple[str | None, str | None]:
        """Returns (one-line summary, full trace), both redacted."""
        if not flink_job_id:
            return None, None
        try:
            detail = await self._cluster.job_detail(flink_job_id)
        except Exception:
            return None, None
        if detail is None or not detail.exception:
            return None, None
        # During a restart loop rootException is often momentarily empty, so take
        # the first line that names a real cause rather than the first line at all.
        lines = [ln.strip() for ln in detail.exception.strip().splitlines() if ln.strip()]
        first = next(
            (ln for ln in lines if "Exception" in ln or "Error" in ln),
            lines[0] if lines else "",
        )
        full = self._store.redact(db, detail.exception)
        return self._store.redact(db, first)[:500] or None, full or None


def _catalog_refs(job: Job) -> list[str]:
    try:
        refs = json.loads(job.catalog_refs or "[]")
        return [str(r) for r in refs] if isinstance(refs, list) else []
    except json.JSONDecodeError:
        return []


def _fail(run: JobRun, summary: str, detail: str = "") -> None:
    run.state = RunState.FAILED.value
    run.ended_at = utcnow()
    run.error_summary = summary[:500]
    run.error_detail = detail or None


def _map_state(flink_state: str) -> str:
    s = (flink_state or "").upper()
    if s in ("RESTARTING", "FAILING", "RECONCILING"):
        # Deliberately not RUNNING: Flink reports RESTARTING while a job loops on
        # a failure it cannot recover from, and calling that "running" makes the
        # console lie about the most common real-world failure.
        return RunState.RESTARTING.value
    if s in ("RUNNING", "CREATED", "INITIALIZING"):
        return RunState.RUNNING.value
    if s == "FINISHED":
        return RunState.FINISHED.value
    if s in ("CANCELED", "CANCELLING", "SUSPENDED"):
        return RunState.CANCELED.value
    return RunState.FAILED.value
