"""Request and response shapes for the MARS API."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

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
    labels: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    is_default: bool = False


class TargetOut(BaseModel):
    name: str
    description: str | None
    flink_rest_url: str
    gateway_url: str
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


class ValidateResponse(BaseModel):
    ok: bool
    error: str | None = None
    detail: str | None = None
    warnings: list[WarningOut] = Field(default_factory=list)


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
