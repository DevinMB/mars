"""Jobs: create, edit, validate, run, cancel, and inspect history."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..auth import Principal
from ..cluster import FlinkClusterClient
from ..db import get_session
from ..deps import (
    current_principal,
    get_gateway,
    get_cluster,
    get_secret_store,
    get_submitter,
    get_targets,
    require_writer,
)
from ..ai import AiClient
from ..drafting import draft_statement
from ..gateway import SqlGatewayClient
from ..preview import preview_statement
from ..explain import Context as ExplainContext
from ..explain import explain
from ..guards import check_job, column_names, columns_of
from ..models import CatalogEntry, Job, JobRun, JobVersion, RunState, Schedule
from ..schemas import (
    CheckpointOut,
    DraftJobIn,
    DraftRequest,
    DraftResponse,
    NestedFieldOut,
    PreviewRequest,
    SampleOut,
    DiagnosticsOut,
    JobIn,
    JobOut,
    RunOut,
    ScheduleIn,
    ScheduleOut,
    ValidateResponse,
    VertexOut,
    WarningOut,
)
from ..routes.ai import _row as ai_row
from ..routes.ai import config_for as ai_config
from ..secrets import SecretStore
from ..submitter import JobSubmitter, SubmissionError
from ..targets import TargetRegistry, UnknownTargetError

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# States in which a job occupies a slot and must not be started a second time.
_ACTIVE = (RunState.RUNNING.value, RunState.SUBMITTING.value, RunState.RESTARTING.value)


def _refs(job: Job) -> list[str]:
    try:
        v = json.loads(job.catalog_refs or "[]")
        return [str(x) for x in v] if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


def _run_out(run: JobRun | None) -> RunOut | None:
    if run is None:
        return None
    return RunOut(
        id=run.id,
        job_version=run.job_version,
        flink_job_id=run.flink_job_id,
        state=run.state,
        started_at=run.started_at,
        ended_at=run.ended_at,
        error_summary=run.error_summary,
        restarts=run.restarts,
        triggered_by_schedule=run.triggered_by_schedule,
        submitted_by=run.submitted_by,
        savepoint_path=run.savepoint_path,
        restored_from=run.restored_from,
    )


def _schedule_out(s: Schedule | None) -> ScheduleOut | None:
    if s is None:
        return None
    return ScheduleOut(
        mode=s.mode,
        cron_expr=s.cron_expr,
        timezone_name=s.timezone_name,
        enabled=s.enabled,
        last_fire_at=s.last_fire_at,
        next_fire_at=s.next_fire_at,
    )


def _out(job: Job) -> JobOut:
    latest = job.runs[0] if job.runs else None
    return JobOut(
        id=job.id,
        name=job.name,
        description=job.description,
        job_type=job.job_type,
        sql_text=job.sql_text,
        catalog_refs=_refs(job),
        enabled=job.enabled,
        version=job.version,
        target_name=job.target_name,
        latest_savepoint=job.latest_savepoint,
        updated_at=job.updated_at,
        latest_run=_run_out(latest),
        schedule=_schedule_out(job.schedule),
    )


def _get(db: Session, name: str) -> Job:
    job = db.query(Job).filter(Job.name == name).one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job named '{name}'")
    return job


def _validate_refs(db: Session, refs: list[str]) -> None:
    if not refs:
        return
    known = {
        n for (n,) in db.query(CatalogEntry.name).filter(CatalogEntry.name.in_(refs)).all()
    }
    missing = [r for r in refs if r not in known]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown catalog entries: {', '.join(missing)}",
        )


@router.get("", response_model=list[JobOut])
async def list_jobs(
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
    cluster: FlinkClusterClient = Depends(get_cluster),
) -> list[JobOut]:
    jobs = db.query(Job).order_by(Job.name).all()
    out = [_out(j) for j in jobs]

    # Overlay what the cluster currently reports, so a job that died overnight is
    # not still shown as running.
    try:
        live = {o.job_id: o for o in await cluster.list_jobs()}
    except Exception:
        return out

    running: list[str] = []
    for item in out:
        fid = item.latest_run.flink_job_id if item.latest_run else None
        if fid and fid in live:
            item.live_state = live[fid].state
            if live[fid].state == "RUNNING":
                running.append(fid)

    # Checkpoint age is the earliest visible sign that a job has stopped making
    # progress while still claiming to run, so it belongs on the list rather than
    # one click into each job.
    try:
        ages = await cluster.checkpoint_ages(running)
    except Exception:
        return out

    for item in out:
        fid = item.latest_run.flink_job_id if item.latest_run else None
        if fid in ages:
            item.checkpoint_age_ms = ages[fid]
    return out


@router.get("/{name}", response_model=JobOut)
def get_job(
    name: str,
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
) -> JobOut:
    return _out(_get(db, name))


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(
    body: JobIn,
    principal: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
) -> JobOut:
    if db.query(Job).filter(Job.name == body.name).count():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A job named '{body.name}' already exists.",
        )
    _validate_refs(db, body.catalog_refs)

    job = Job(
        name=body.name,
        description=body.description,
        job_type=body.job_type,
        sql_text=body.sql_text,
        catalog_refs=json.dumps(body.catalog_refs),
        created_by=principal.username,
        target_name=body.target_name or None,
        version=1,
    )
    db.add(job)
    db.flush()
    db.add(
        JobVersion(
            job_id=job.id,
            version=1,
            sql_text=job.sql_text,
            catalog_refs=job.catalog_refs,
            note=body.note or "Created",
            created_by=principal.username,
        )
    )
    db.commit()
    return _out(job)


@router.put("/{name}", response_model=JobOut)
def update_job(
    name: str,
    body: JobIn,
    principal: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
) -> JobOut:
    job = _get(db, name)
    _validate_refs(db, body.catalog_refs)

    new_refs = json.dumps(body.catalog_refs)
    changed = body.sql_text != job.sql_text or new_refs != job.catalog_refs

    job.description = body.description
    job.job_type = body.job_type
    job.sql_text = body.sql_text
    job.catalog_refs = new_refs
    job.target_name = body.target_name or None

    # Only a change to what actually runs earns a new version; renaming the
    # description should not fill the history with noise.
    if changed:
        job.version += 1
        db.add(
            JobVersion(
                job_id=job.id,
                version=job.version,
                sql_text=job.sql_text,
                catalog_refs=job.catalog_refs,
                note=body.note,
                created_by=principal.username,
            )
        )
    db.commit()
    return _out(job)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def delete_job(
    name: str,
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
    targets: TargetRegistry = Depends(get_targets),
) -> None:
    job = _get(db, name)
    running = [
        r for r in job.runs
        if r.state in _ACTIVE
    ]
    if running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This job is still running. Cancel it before deleting.",
        )
    db.delete(job)
    db.commit()


@router.get("/{name}/script")
def preview_script(
    name: str,
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
    targets: TargetRegistry = Depends(get_targets),
) -> dict:
    """The exact statements that will be sent, with secrets still as placeholders."""
    job = _get(db, name)
    try:
        return {"statements": targets.for_job_submitter(db, job).build_script(db, job)}
    except SubmissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{name}/validate", response_model=ValidateResponse)
async def validate_job(
    name: str,
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
    targets: TargetRegistry = Depends(get_targets),
) -> ValidateResponse:
    job = _get(db, name)
    warnings = [
        WarningOut(level=w.level, code=w.code, message=w.message) for w in check_job(db, job)
    ]
    try:
        await targets.for_job_submitter(db, job).validate(db, job)
    except SubmissionError as exc:
        return _validated(db, job.sql_text, _refs(job), warnings, exc)
    return ValidateResponse(ok=True, warnings=warnings)


def _explanation_context(db: Session, refs: list[str]) -> ExplainContext:
    """What the console knows that Flink does not.

    Table suggestions come from the whole catalog rather than only the tables this
    job declares, because the most common cause of "no such table" is precisely
    that the table exists but was never ticked.
    """
    tables = [name for (name,) in db.query(CatalogEntry.name).all()]
    columns: list[str] = []
    if refs:
        for entry in db.query(CatalogEntry).filter(CatalogEntry.name.in_(refs)).all():
            columns.extend(column_names(entry.sql_text))
    return ExplainContext(tables=tables, columns=sorted(set(columns)))


def _statement_offset(sql_text: str, statement: str) -> tuple[int, int]:
    """Where the failing statement begins inside what the user typed.

    Flink numbers lines from the start of the statement it was given, and a job's
    SQL is split before submission, so for anything but the first statement those
    numbers land on the wrong line in the editor. Returns (lines, columns) to add.
    When the statement cannot be located the offset is zero and the marker simply
    stays where Flink put it -- a marker slightly off is better than none.
    """
    needle = (statement or "").strip()
    if not needle:
        return 0, 0
    index = sql_text.find(needle)
    if index < 0:
        head = needle.split("\n")[0].strip()
        index = sql_text.find(head) if head else -1
        if index < 0:
            return 0, 0
    before = sql_text[:index]
    line_offset = before.count("\n")
    column_offset = index - (before.rfind("\n") + 1)
    return line_offset, column_offset


def _validated(
    db: Session, sql_text: str, refs: list[str], warnings: list[WarningOut],
    exc: SubmissionError | None,
) -> ValidateResponse:
    if exc is None:
        return ValidateResponse(ok=True, warnings=warnings)

    ex = explain(exc.summary, exc.detail or "", _explanation_context(db, refs))

    line, column = ex.line, ex.column
    end_line, end_column = ex.end_line, ex.end_column
    if line is not None:
        dl, dc = _statement_offset(sql_text, getattr(exc, "statement", ""))
        # A column offset only applies to the statement's own first line.
        column = (column + dc) if line == 1 and column is not None else column
        if end_line == 1 and end_column is not None:
            end_column = end_column + dc
        line += dl
        if end_line is not None:
            end_line += dl

    return ValidateResponse(
        ok=False,
        error=ex.message,
        original_error=ex.original,
        detail=exc.detail or None,
        hint=ex.hint,
        code=ex.code,
        line=line,
        column=column,
        end_line=end_line,
        end_column=end_column,
        suggestions=ex.suggestions,
        warnings=warnings,
    )


@router.post("/validate", response_model=ValidateResponse)
async def validate_draft(
    body: DraftJobIn,
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
    targets: TargetRegistry = Depends(get_targets),
) -> ValidateResponse:
    """Checks a job that has not been saved, so the editor can check as you type.

    Unsaved on purpose: the existing per-job endpoint can only check something
    already written to the database, which means the first time anyone learns a
    statement is wrong is after they have saved it and navigated away.
    """
    if not body.sql_text.strip():
        return ValidateResponse(ok=True)

    # Transient and never added to the session: this must not create a job, and
    # must not leave a half-built one behind if validation throws.
    draft = Job(
        name=body.name or "draft",
        sql_text=body.sql_text,
        job_type=body.job_type,
        catalog_refs=json.dumps(body.catalog_refs),
        target_name=body.target_name or None,
    )
    existing = db.query(Job).filter(Job.name == draft.name).one_or_none()
    if existing is not None:
        # So "another job writes this topic" does not fire against itself.
        draft.id = existing.id

    warnings = [
        WarningOut(level=w.level, code=w.code, message=w.message)
        for w in check_job(db, draft)
    ]
    try:
        submitter = targets.for_job_submitter(db, draft)
    except UnknownTargetError as exc:
        return ValidateResponse(ok=False, error=str(exc), warnings=warnings)

    try:
        await submitter.validate(db, draft)
    except SubmissionError as exc:
        return _validated(db, body.sql_text, body.catalog_refs, warnings, exc)
    return ValidateResponse(ok=True, warnings=warnings)


@router.post("/draft", response_model=DraftResponse)
async def draft_job(
    body: DraftRequest,
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
    targets: TargetRegistry = Depends(get_targets),
    store: SecretStore = Depends(get_secret_store),
) -> DraftResponse:
    """Drafts a statement from a description, and checks it before returning it.

    Requires write access: someone who cannot create a job has no reason to
    generate one, and this spends time on a model and on the planner.

    The result is a draft. It is returned as text and nothing here can submit it.
    """
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Describe what the job should do.")

    row = ai_row(db)
    config = ai_config(db, store, row)
    if not row.enabled or not config.configured:
        raise HTTPException(
            status_code=409,
            detail=(
                "No AI provider is enabled. An administrator sets one up under AI."
            ),
        )

    entries = {
        e.name: e
        for e in db.query(CatalogEntry)
        .filter(CatalogEntry.name.in_(body.catalog_refs))
        .all()
    } if body.catalog_refs else {}

    tables = [
        {
            "name": e.name,
            "kind": e.kind,
            "columns": [{"name": n, "type": t} for n, t in columns_of(e.sql_text)],
            "document_fields": body.document_fields.get(e.name, {}),
        }
        for e in entries.values()
    ]

    async def _validate(sql: str) -> tuple[bool, str | None, str | None]:
        candidate = Job(
            name=body.name or "draft",
            sql_text=sql,
            job_type=body.job_type,
            catalog_refs=json.dumps(body.catalog_refs),
            target_name=body.target_name or None,
        )
        try:
            await targets.for_job_submitter(db, candidate).validate(db, candidate)
        except SubmissionError as exc:
            checked = _validated(db, sql, body.catalog_refs, [], exc)
            return False, checked.error, checked.hint
        except UnknownTargetError as exc:
            return False, str(exc), None
        return True, None, None

    result = await draft_statement(
        AiClient(config), body.prompt, tables, body.job_type, _validate,
        current_sql=body.current_sql,
    )
    return DraftResponse(
        sql=result.sql,
        ok=result.ok,
        amended=result.amended,
        error=store.redact(db, result.error) if result.error else None,
        hint=result.hint,
        attempts=result.attempts,
        notes=[store.redact(db, n) for n in result.notes],
    )


@router.post("/preview", response_model=SampleOut)
async def preview_statement_route(
    body: PreviewRequest,
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
    gateway: SqlGatewayClient = Depends(get_gateway),
    store: SecretStore = Depends(get_secret_store),
) -> SampleOut:
    """Shows the rows a statement would produce, without writing them anywhere.

    Only the source tables are created for this: the sink is never defined, so a
    preview cannot write to Kafka, a database or a light switch. It is unable to
    have a side effect rather than merely declining to.
    """
    if not body.sql_text.strip():
        raise HTTPException(status_code=400, detail="There is no statement to preview.")

    sources = [
        e
        for e in db.query(CatalogEntry)
        .filter(CatalogEntry.name.in_(body.catalog_refs))
        .all()
        if e.kind == "source"
    ] if body.catalog_refs else []

    result = await preview_statement(
        gateway, store, db, sources, body.sql_text,
        limit=body.limit, start=body.start,
    )
    return SampleOut(
        columns=result.columns,
        rows=result.rows,
        nested={
            column: [
                NestedFieldOut(name=f.name, type=f.type, example=f.example)
                for f in fields
            ]
            for column, fields in result.nested.items()
        },
        error=result.error,
    )


@router.post("/{name}/run", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
async def run_job(
    name: str,
    # "latest" resumes from the most recent savepoint; "none" starts with empty
    # state; anything else is treated as an explicit savepoint path.
    from_savepoint: str = "latest",
    principal: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
    targets: TargetRegistry = Depends(get_targets),
) -> RunOut:
    job = _get(db, name)
    if not job.enabled:
        raise HTTPException(status_code=409, detail="This job is disabled.")

    already = [
        r for r in job.runs
        if r.state in _ACTIVE
    ]
    if already:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This job is already running. Running a second copy would duplicate "
                "its output; cancel the current run first."
            ),
        )

    if from_savepoint == "none":
        savepoint = None
    elif from_savepoint in ("latest", ""):
        savepoint = job.latest_savepoint
    else:
        savepoint = from_savepoint

    try:
        run = await targets.for_job_submitter(db, job).submit(
            db, job, submitted_by=principal.username, savepoint_path=savepoint
        )
    except SubmissionError as exc:
        raise HTTPException(status_code=400, detail=exc.summary) from exc
    return _run_out(run)  # type: ignore[return-value]


@router.post("/{name}/cancel", status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def cancel_job(
    name: str,
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
    targets: TargetRegistry = Depends(get_targets),
) -> None:
    job = _get(db, name)
    active = next(
        (r for r in job.runs
         if r.state in _ACTIVE),
        None,
    )
    if active is None:
        raise HTTPException(status_code=409, detail="This job is not running.")
    await targets.for_job_submitter(db, job).cancel(db, active)


@router.post("/{name}/stop", response_model=RunOut)
async def stop_job(
    name: str,
    drain: bool = False,
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
    targets: TargetRegistry = Depends(get_targets),
) -> RunOut:
    """Saves the job's state, then stops it, so it can resume where it left off.

    ``drain`` advances the watermark to the end of time first, flushing pending
    windows. Correct when retiring a job for good; wrong when it is coming back,
    because event time cannot go backwards after that.
    """
    job = _get(db, name)
    active = next((r for r in job.runs if r.state in _ACTIVE), None)
    if active is None:
        raise HTTPException(status_code=409, detail="This job is not running.")

    try:
        await targets.for_job_submitter(db, job).stop_with_savepoint(
            db, active, drain=drain
        )
    except SubmissionError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{exc.summary} {exc.detail}".strip(),
        ) from exc
    return _run_out(active)  # type: ignore[return-value]


@router.get("/{name}/savepoints")
def list_savepoints(
    name: str,
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
) -> dict:
    job = _get(db, name)
    saved = [
        {
            "run_id": r.id,
            "path": r.savepoint_path,
            "taken_at": r.ended_at,
            "job_version": r.job_version,
        }
        for r in job.runs
        if r.savepoint_path
    ]
    return {"latest": job.latest_savepoint, "savepoints": saved}


@router.get("/{name}/runs", response_model=list[RunOut])
def list_runs(
    name: str,
    limit: int = 50,
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
) -> list[RunOut]:
    job = _get(db, name)
    return [_run_out(r) for r in job.runs[: max(1, min(limit, 200))]]  # type: ignore[misc]


@router.get("/{name}/runs/{run_id}")
def get_run(
    name: str,
    run_id: int,
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
) -> dict:
    job = _get(db, name)
    run = next((r for r in job.runs if r.id == run_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail="No such run for this job")
    out = _run_out(run).model_dump()  # type: ignore[union-attr]
    out["error_detail"] = run.error_detail
    return out


@router.get("/{name}/diagnostics", response_model=DiagnosticsOut)
async def job_diagnostics(
    name: str,
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
    targets: TargetRegistry = Depends(get_targets),
    store: SecretStore = Depends(get_secret_store),
) -> DiagnosticsOut:
    """Everything the cluster knows about this job's most recent run.

    Answers "why is it not working?" without leaving MARS: checkpoint health
    against the job's own configured interval, per-operator backpressure and
    throughput, consumer lag, and the full stack trace.
    """
    job = _get(db, name)
    run = job.runs[0] if job.runs else None
    if run is None or not run.flink_job_id:
        return DiagnosticsOut(available=False, reason="This job has not run yet.")

    try:
        target = targets.for_job(db, job)
    except UnknownTargetError as e:
        return DiagnosticsOut(available=False, reason=str(e))

    path = f"/#/job/{run.flink_job_id}/overview"
    out = DiagnosticsOut(
        flink_job_id=run.flink_job_id,
        target=target.name,
        # Only absolute when the target says where a browser can reach it. Building
        # one from flink_rest_url is what produced links to "http://jobmanager:8081",
        # which resolves only inside the container network. When it is unset the
        # console derives the host from its own address instead.
        flink_ui_url=f"{target.ui_url.rstrip('/')}{path}" if target.ui_url else None,
        flink_ui_port=_port_of(target.flink_rest_url),
        flink_ui_path=path,
    )

    try:
        detail = await targets.cluster(target).job_detail(run.flink_job_id)
    except Exception:
        # The run's own record is still worth showing when the cluster is down.
        out.reason = f"Cluster {target.name} is unreachable."
        out.exception = _redacted(db, store, run.error_detail or run.error_summary)
        return out

    if detail is None:
        # Flink keeps finished jobs only as long as its history allows.
        out.reason = "The cluster no longer has this job; it may have been pruned."
        out.exception = _redacted(db, store, run.error_detail or run.error_summary)
        return out

    out.available = True
    out.state = detail.overview.state
    out.uptime_ms = detail.overview.duration_ms
    out.restarts = detail.restarts if detail.restarts is not None else run.restarts
    out.checkpoints = CheckpointOut(
        completed=detail.checkpoints.completed,
        failed=detail.checkpoints.failed,
        in_progress=detail.checkpoints.in_progress,
        restored=detail.checkpoints.restored,
        latest_completed_age_ms=detail.checkpoints.latest_completed_age_ms,
        latest_completed_size_bytes=detail.checkpoints.latest_completed_size_bytes,
        latest_completed_duration_ms=detail.checkpoints.latest_completed_duration_ms,
        interval_ms=detail.checkpoints.interval_ms,
        timeout_ms=detail.checkpoints.timeout_ms,
        stalled=detail.checkpoints.stalled,
    )
    out.vertices = [VertexOut(**vars(v)) for v in detail.vertices]
    out.exception = _redacted(
        db, store, detail.exception or run.error_detail or run.error_summary
    )
    return out


def _port_of(url: str) -> int | None:
    """The port MARS reaches this cluster on, as a hint for the browser's link.

    The stock compose file publishes the Flink UI on the same port it serves it
    internally, so this guesses right for a default deployment. A deployment that
    remaps the port or fronts it with a proxy sets the target's ui_url instead.
    """
    try:
        return urlsplit(url).port or (443 if urlsplit(url).scheme == "https" else 80)
    except ValueError:
        return None


def _redacted(db: Session, store: SecretStore, text: str | None) -> str | None:
    """A Flink trace readily echoes table options back, passwords included."""
    if not text:
        return None
    return store.redact(db, text)


@router.get("/{name}/versions")
def list_versions(
    name: str,
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
) -> list[dict]:
    job = _get(db, name)
    return [
        {
            "version": v.version,
            "sql_text": v.sql_text,
            "catalog_refs": json.loads(v.catalog_refs or "[]"),
            "note": v.note,
            "created_at": v.created_at,
            "created_by": v.created_by,
        }
        for v in job.versions
    ]


@router.put("/{name}/schedule", response_model=ScheduleOut)
def set_schedule(
    name: str,
    body: ScheduleIn,
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
) -> ScheduleOut:
    job = _get(db, name)

    if body.mode == "cron":
        if not body.cron_expr:
            raise HTTPException(status_code=400, detail="A cron schedule needs an expression.")
        try:
            from croniter import croniter

            if not croniter.is_valid(body.cron_expr):
                raise ValueError
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"'{body.cron_expr}' is not a valid cron expression.",
            ) from exc
        if job.job_type == "streaming":
            raise HTTPException(
                status_code=400,
                detail=(
                    "A streaming job runs continuously, so a cron schedule would keep "
                    "starting copies of it. Use supervisor mode to keep it running."
                ),
            )

    sched = job.schedule or Schedule(job_id=job.id)
    sched.mode = body.mode
    sched.cron_expr = body.cron_expr
    sched.timezone_name = body.timezone_name
    sched.enabled = body.enabled
    db.add(sched)
    db.commit()
    return _schedule_out(sched)  # type: ignore[return-value]


@router.delete("/{name}/schedule", status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def clear_schedule(
    name: str,
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
) -> None:
    job = _get(db, name)
    if job.schedule is None:
        raise HTTPException(status_code=404, detail="This job has no schedule.")
    db.delete(job.schedule)
    db.commit()
