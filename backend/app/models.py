"""Persistent model for the MARS console.

Shape worth knowing:

* A **CatalogEntry** is one ``CREATE TABLE`` -- a source or a sink. Jobs reference
  entries by name and the console replays that DDL ahead of each submission, which
  is how table definitions survive the SQL Gateway's ephemeral sessions.
* A **Job** holds the current SQL; every save also writes a **JobVersion**, so a
  job that starts failing can be compared against what it looked like before.
* A **JobRun** records one submission and its Flink job id, which is the link
  between something a user pressed and something the cluster is doing.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class JobType(str, enum.Enum):
    STREAMING = "streaming"
    BATCH = "batch"


class ScheduleMode(str, enum.Enum):
    # Fire a bounded job on a cron expression.
    CRON = "cron"
    # Keep a streaming job running, restarting it from its latest savepoint.
    SUPERVISOR = "supervisor"


class RunState(str, enum.Enum):
    SUBMITTING = "submitting"
    RUNNING = "running"
    # Flink keeps restarting the job's tasks. It is not healthy, and reporting it
    # as RUNNING hides the single most common way a stream job fails: it starts
    # fine, then cannot reach something it needs.
    RESTARTING = "restarting"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELED = "canceled"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Target(Base, TimestampMixin):
    """A Flink cluster jobs can be sent to.

    Placement in Flink is not what it first sounds like. A session cluster's
    scheduler puts tasks in whatever slot is free, and there is no supported way to
    say "this job belongs on that machine". Slot sharing groups control placement
    *within* one job; fine-grained resource management controls slot *sizing*.
    Neither pins a job to a host.

    So placement means choosing which cluster receives the job, and a target is that
    choice made explicit: a small cluster for light jobs and a large one for heavy
    state, or one cluster per machine. The same model carries over to Kubernetes
    later, where a target maps to a deployment with real node affinity.
    """

    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(512))
    flink_rest_url: Mapped[str] = mapped_column(String(512))
    gateway_url: Mapped[str] = mapped_column(String(512))
    # Free-form labels, e.g. {"zone": "rack-1", "profile": "memory"}. Not used for
    # routing yet; they exist so a fleet can be described before it needs to be.
    labels: Mapped[str] = mapped_column(Text, default="{}")
    # Exactly one target is the default; jobs that name none are sent there.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default=Role.ADMIN.value)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when the account was created with a generated password that the operator
    # has not yet replaced; the console nags until it is cleared.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)

    tokens: Mapped[list["ApiToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ApiToken(Base, TimestampMixin):
    """A bearer token for automation. Only its hash is stored."""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    # Shown in the UI so a token can be identified without revealing it.
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    token_hash: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="tokens")


class Secret(Base, TimestampMixin):
    """A credential, encrypted at rest.

    Connection passwords must never sit in the SQL text of a job: that text is
    listed, diffed and shown in the editor. Jobs reference ``${secret:name}`` and
    the value is substituted only at submission time.
    """

    __tablename__ = "secrets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255))
    ciphertext: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(64))


class CatalogEntry(Base, TimestampMixin):
    """One source or sink table definition."""

    __tablename__ = "catalog_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # source | sink
    connector: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str | None] = mapped_column(String(512))
    # The full CREATE TABLE. Generated from the connector form, then editable by
    # hand -- the form is a convenience, never a cage.
    sql_text: Mapped[str] = mapped_column(Text)
    # The form values it was generated from, so the form can be reopened.
    options_json: Mapped[str] = mapped_column(Text, default="{}")
    created_by: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (UniqueConstraint("name", name="uq_catalog_name"),)


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(512))
    job_type: Mapped[str] = mapped_column(String(16), default=JobType.STREAMING.value)
    sql_text: Mapped[str] = mapped_column(Text)
    # Names of the catalog entries replayed before this job's statement.
    catalog_refs: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(String(64))
    # Which cluster this job runs on. Null means the default target, which is what
    # every existing job gets: adding this while everything is implicitly "default"
    # is a nullable column and a dropdown, where retrofitting it later would be a
    # migration plus a decision per job.
    target_name: Mapped[str | None] = mapped_column(String(64), index=True)

    versions: Mapped[list["JobVersion"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobVersion.version.desc()"
    )
    runs: Mapped[list["JobRun"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobRun.id.desc()"
    )
    schedule: Mapped["Schedule | None"] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )


class JobVersion(Base):
    __tablename__ = "job_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    sql_text: Mapped[str] = mapped_column(Text)
    catalog_refs: Mapped[str] = mapped_column(Text, default="[]")
    note: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(64))

    job: Mapped[Job] = relationship(back_populates="versions")

    __table_args__ = (UniqueConstraint("job_id", "version", name="uq_job_version"),)


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    job_version: Mapped[int] = mapped_column(Integer)
    # Flink's own 32-character job id; null until the cluster accepts it.
    flink_job_id: Mapped[str | None] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(16), default=RunState.SUBMITTING.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The one-line summary, with the full trace kept beside it.
    error_summary: Mapped[str | None] = mapped_column(String(512))
    error_detail: Mapped[str | None] = mapped_column(Text)
    # How many times the cluster has been seen restarting this job. A number that
    # keeps climbing is a restart loop, not a transient blip.
    restarts: Mapped[int] = mapped_column(Integer, default=0)
    # True when the scheduler started this rather than a person.
    triggered_by_schedule: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_by: Mapped[str | None] = mapped_column(String(64))

    job: Mapped[Job] = relationship(back_populates="runs")


class Schedule(Base, TimestampMixin):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True
    )
    mode: Mapped[str] = mapped_column(String(16), default=ScheduleMode.CRON.value)
    cron_expr: Mapped[str | None] = mapped_column(String(128))
    timezone_name: Mapped[str] = mapped_column(String(64), default="UTC")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_fire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[Job] = relationship(back_populates="schedule")
