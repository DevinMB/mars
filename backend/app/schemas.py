"""Request and response shapes for the MARS API."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import BaseModel, Field, PlainSerializer, field_validator


def _as_utc_iso(dt: datetime) -> str:
    """Serialises a datetime as unambiguous UTC.

    Everything is stored in UTC, but SQLite does not preserve tzinfo, so values
    come back naive. Emitting them bare produces strings like
    "2026-09-14T21:20:15", and a browser reads a timezone-less string as *local*
    time -- which put every timestamp four hours in the future for a UTC-4 client
    and made the console report jobs as having last run "in the future" with a
    duration of 0s. Attaching the zone here fixes it for every endpoint at once.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


# Use this instead of a bare datetime in any response model.
UtcDatetime = Annotated[datetime, PlainSerializer(_as_utc_iso, return_type=str)]


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12)


class MeResponse(BaseModel):
    username: str
    role: str
    must_change_password: bool


class SecretIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1)
    description: str | None = None


class SecretOut(BaseModel):
    name: str
    description: str | None
    created_by: str | None
    updated_at: UtcDatetime
    # The value is never returned. Not to admins, not to anyone.


class ColumnIn(BaseModel):
    name: str
    sqlType: str = "STRING"


class CatalogEntryIn(BaseModel):
    name: str
    kind: str
    connector: str
    description: str | None = None
    options: dict[str, str] = Field(default_factory=dict)
    columns: list[ColumnIn] = Field(default_factory=list)
    # Supplied instead of options/columns when a user hand-writes the DDL.
    sql_text: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in ("source", "sink"):
            raise ValueError("kind must be 'source' or 'sink'")
        return v


class ColumnOut(BaseModel):
    name: str
    type: str


class CatalogEntryOut(BaseModel):
    id: int
    name: str
    kind: str
    connector: str
    description: str | None
    sql_text: str
    options: dict[str, str]
    updated_at: UtcDatetime
    used_by: list[str] = Field(default_factory=list)
    # Declared in the DDL. For a raw-passthrough source this is just the envelope
    # (`record_key`, `doc`); what is inside the document needs a sample.
    columns: list[ColumnOut] = Field(default_factory=list)


class NestedFieldOut(BaseModel):
    name: str
    type: str
    example: str | None = None


class SampleOut(BaseModel):
    """A handful of real records, so a job can be written against facts."""

    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    # Field names found inside JSON documents, per column.
    nested: dict[str, list[NestedFieldOut]] = Field(default_factory=dict)
    error: str | None = None


class JobIn(BaseModel):
    name: str
    description: str | None = None
    job_type: str = "streaming"
    sql_text: str
    catalog_refs: list[str] = Field(default_factory=list)
    note: str | None = None
    # None means the default target.
    target_name: str | None = None

    @field_validator("job_type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in ("streaming", "batch"):
            raise ValueError("job_type must be 'streaming' or 'batch'")
        return v


class RunOut(BaseModel):
    id: int
    job_version: int
    flink_job_id: str | None
    state: str
    started_at: UtcDatetime
    ended_at: UtcDatetime | None
    error_summary: str | None
    restarts: int = 0
    triggered_by_schedule: bool
    submitted_by: str | None
    # Where this run's state was saved when it was stopped, and where it resumed
    # from when it started. Both null for a stateless job nobody bothered to save.
    savepoint_path: str | None = None
    restored_from: str | None = None


class CheckpointOut(BaseModel):
    completed: int = 0
    failed: int = 0
    in_progress: int = 0
    restored: int = 0
    latest_completed_age_ms: int | None = None
    latest_completed_size_bytes: int | None = None
    latest_completed_duration_ms: int | None = None
    interval_ms: int | None = None
    timeout_ms: int | None = None
    stalled: bool = False


class VertexOut(BaseModel):
    id: str
    name: str
    status: str = ""
    parallelism: int = 0
    backpressure_level: str | None = None
    busy_ratio: float | None = None
    backpressured_ratio: float | None = None
    records_in: int | None = None
    records_out: int | None = None
    records_in_rate: float | None = None
    records_out_rate: float | None = None
    kafka_lag_max: float | None = None


class DiagnosticsOut(BaseModel):
    """What the console needs to answer "why is this job not working?"."""

    available: bool = False
    # Why diagnostics could not be gathered, when they could not be.
    reason: str | None = None
    flink_job_id: str | None = None
    target: str | None = None
    state: str | None = None
    uptime_ms: int | None = None
    restarts: int | None = None
    checkpoints: CheckpointOut | None = None
    vertices: list[VertexOut] = []
    # Full stack trace, with any known secret value replaced by its placeholder.
    exception: str | None = None
    # Absolute, and only when the target declares a browser-reachable address.
    # Otherwise the console builds the link from its own location -- the backend
    # cannot know what the viewer's browser can resolve.
    flink_ui_url: str | None = None
    flink_ui_port: int | None = None
    flink_ui_path: str | None = None


class ScheduleIn(BaseModel):
    mode: str = "cron"
    cron_expr: str | None = None
    timezone_name: str = "UTC"
    enabled: bool = True

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in ("cron", "supervisor"):
            raise ValueError("mode must be 'cron' or 'supervisor'")
        return v


class ScheduleOut(BaseModel):
    mode: str
    cron_expr: str | None
    timezone_name: str
    enabled: bool
    last_fire_at: UtcDatetime | None
    next_fire_at: UtcDatetime | None


class JobOut(BaseModel):
    id: int
    name: str
    description: str | None
    job_type: str
    sql_text: str
    catalog_refs: list[str]
    enabled: bool
    version: int
    target_name: str | None = None
    # The most recent state saved for this job. Its presence is what makes a
    # restart resume where it left off rather than start over with empty state.
    latest_savepoint: str | None = None
    updated_at: UtcDatetime
    latest_run: RunOut | None = None
    schedule: ScheduleOut | None = None
    # Live state from the cluster, when it is reachable.
    live_state: str | None = None
    checkpoint_age_ms: int | None = None


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
    role: str = "editor"
    # Omit to have one generated and returned once.
    password: str | None = Field(default=None, min_length=12)

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ("admin", "editor", "viewer"):
            raise ValueError("role must be admin, editor or viewer")
        return v


class UserUpdate(BaseModel):
    role: str | None = None
    disabled: bool | None = None

    @field_validator("role")
    @classmethod
    def _role(cls, v: str | None) -> str | None:
        if v is not None and v not in ("admin", "editor", "viewer"):
            raise ValueError("role must be admin, editor or viewer")
        return v


class UserOut(BaseModel):
    username: str
    role: str
    disabled: bool
    must_change_password: bool
    last_login_at: UtcDatetime | None
    created_at: UtcDatetime
    token_count: int = 0
    is_self: bool = False


class PasswordResetOut(BaseModel):
    username: str
    # Returned once, when MARS generated it. Null when the caller set one.
    password: str | None


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    expires_days: int | None = Field(default=None, ge=1, le=3650)


class TokenOut(BaseModel):
    name: str
    prefix: str
    created_at: UtcDatetime
    expires_at: UtcDatetime | None
    last_used_at: UtcDatetime | None
    # Only on creation, and never again.
    token: str | None = None


class TargetIn(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    description: str | None = None
    flink_rest_url: str
    gateway_url: str
    ui_url: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    is_default: bool = False


class TargetOut(BaseModel):
    name: str
    description: str | None
    flink_rest_url: str
    gateway_url: str
    ui_url: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    enabled: bool
    is_default: bool
    job_count: int = 0
    # Live, when the cluster answers.
    reachable: bool | None = None
    flink_version: str | None = None
    slots_total: int | None = None
    slots_available: int | None = None


class TargetProbeIn(BaseModel):
    flink_rest_url: str
    gateway_url: str


class TargetProbeOut(BaseModel):
    """What a URL pair looks like from the console, before anything is saved."""

    flink_ok: bool
    flink_detail: str
    gateway_ok: bool
    gateway_detail: str
    flink_version: str | None = None
    slots_total: int | None = None


class WarningOut(BaseModel):
    """A non-blocking caution shown next to a job before it is run."""

    level: str  # "warning" | "danger"
    code: str
    message: str


class DraftRequest(BaseModel):
    """A description of a job, plus the tables it is allowed to use."""

    prompt: str
    catalog_refs: list[str] = Field(default_factory=list)
    job_type: str = "streaming"
    target_name: str | None = None
    name: str = "draft"
    # Field names found inside JSON documents, keyed table -> column -> fields.
    # Supplied by the console from any samples the user has already taken, so the
    # model is told what is in a document rather than guessing at it.
    document_fields: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    # The statement as it stands. When present the model is asked to change it
    # rather than write a new one, so a small request stays a small change.
    current_sql: str = ""


class DraftResponse(BaseModel):
    sql: str = ""
    ok: bool = False
    amended: bool = False
    error: str | None = None
    hint: str | None = None
    attempts: int = 0
    notes: list[str] = Field(default_factory=list)


class PreviewRequest(BaseModel):
    """A statement to run without writing anything, plus the tables it reads."""

    sql_text: str
    catalog_refs: list[str] = Field(default_factory=list)
    target_name: str | None = None
    limit: int = 20
    # earliest replays from the start of the topic; latest waits for new records.
    start: str = "earliest"


class ImportRequest(BaseModel):
    yaml_text: str
    # Defaults to a dry run: this writes over definitions jobs are running from,
    # and seeing the list first is the difference between an import and an accident.
    dry_run: bool = True
    # Without this, entries that already exist are left alone, so importing into a
    # populated installation is additive rather than destructive.
    replace: bool = False


class ImportResult(BaseModel):
    dry_run: bool
    ok: bool
    created: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    # Secrets the imported definitions reference and this installation lacks.
    missing_secrets: list[str] = Field(default_factory=list)


class AiProviderIn(BaseModel):
    kind: str = "ollama"
    base_url: str = ""
    model: str = ""
    # A name in the secret store, never a key. Keys are entered under Secrets.
    secret_name: str | None = None
    enabled: bool = False
    timeout_seconds: int = 120
    auth_method: str = "none"
    auth_header: str = ""
    auth_username: str = ""
    extra_headers: dict[str, str] = Field(default_factory=dict)
    temperature: str = "0"
    max_tokens: int = 1500

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        from .ai import KINDS

        if v not in KINDS:
            raise ValueError(f"kind must be one of: {', '.join(KINDS)}")
        return v

    @field_validator("auth_method")
    @classmethod
    def _auth(cls, v: str) -> str:
        from .ai import AUTH_METHODS

        if v not in AUTH_METHODS:
            raise ValueError(f"auth_method must be one of: {', '.join(AUTH_METHODS)}")
        return v


class AiProviderOut(BaseModel):
    kind: str
    base_url: str
    model: str
    secret_name: str | None = None
    enabled: bool
    timeout_seconds: int
    auth_method: str = "none"
    auth_header: str = ""
    auth_username: str = ""
    extra_headers: dict[str, str] = Field(default_factory=dict)
    temperature: str = "0"
    max_tokens: int = 1500
    # True when this is complete enough to use. Features check this rather than
    # inspecting the fields themselves.
    configured: bool = False
    updated_by: str | None = None


class AiStatusOut(BaseModel):
    ok: bool
    detail: str = ""
    models: list[str] = Field(default_factory=list)


class ValidateResponse(BaseModel):
    ok: bool
    # Rewritten into plain language where the failure is one MARS recognises;
    # otherwise Flink's own words, unchanged.
    error: str | None = None
    detail: str | None = None
    hint: str | None = None
    code: str | None = None
    # Flink's own wording, kept so a rewrite can never hide the real message.
    original_error: str | None = None
    # 1-based, already mapped onto the statement as the user typed it.
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    suggestions: list[str] = Field(default_factory=list)
    warnings: list[WarningOut] = Field(default_factory=list)


class DraftJobIn(BaseModel):
    """An unsaved job, for checking while it is still being written."""

    name: str = "draft"
    sql_text: str = ""
    catalog_refs: list[str] = Field(default_factory=list)
    target_name: str | None = None
    job_type: str = "streaming"


class ClusterOut(BaseModel):
    """Capacity summed across every enabled execution target."""

    reachable: bool
    flink_version: str = ""
    taskmanagers: int = 0
    slots_total: int = 0
    slots_available: int = 0
    jobs_running: int = 0
    targets_total: int = 0
    targets_reachable: int = 0
