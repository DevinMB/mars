"""Request and response shapes for the MARS API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


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
    updated_at: datetime
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
    updated_at: datetime
    used_by: list[str] = Field(default_factory=list)


class JobIn(BaseModel):
    name: str
    description: str | None = None
    job_type: str = "streaming"
    sql_text: str
    catalog_refs: list[str] = Field(default_factory=list)
    note: str | None = None

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
    started_at: datetime
    ended_at: datetime | None
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
    last_fire_at: datetime | None
    next_fire_at: datetime | None


class JobOut(BaseModel):
    id: int
    name: str
    description: str | None
    job_type: str
    sql_text: str
    catalog_refs: list[str]
    enabled: bool
    version: int
    updated_at: datetime
    latest_run: RunOut | None = None
    schedule: ScheduleOut | None = None
    # Live state from the cluster, when it is reachable.
    live_state: str | None = None
    checkpoint_age_ms: int | None = None


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
    reachable: bool
    flink_version: str = ""
    taskmanagers: int = 0
    slots_total: int = 0
    slots_available: int = 0
    jobs_running: int = 0
