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
from dataclasses import dataclass
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


def _aware(value: datetime) -> datetime:
    # SQLite hands timezone-aware columns back naive. They were written as UTC.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class RestorePoint:
    path: str
    kind: str  # "savepoint" or "checkpoint"
    taken_at: datetime


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
    # Where a *browser* can reach this cluster's own web UI, which is rarely where
    # MARS reaches it: the backend talks to "http://jobmanager:8081" over the
    # container network, and a link to that name is unreachable from a laptop.
    # Optional -- when it is unset the console derives one from its own address.
    ui_url: Mapped[str | None] = mapped_column(String(512))
    # Free-form labels, e.g. {"zone": "rack-1", "profile": "memory"}. Not used for
    # routing yet; they exist so a fleet can be described before it needs to be.
    labels: Mapped[str] = mapped_column(Text, default="{}")
    # Exactly one target is the default; jobs that name none are sent there.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AiProvider(Base, TimestampMixin):
    """The model MARS talks to, configured once and used by every AI feature.

    One row. Features that want a model ask for this rather than carrying their
    own endpoint, so switching from a local Ollama to a hosted API is a change in
    one place and every feature follows.

    The credential is not stored here. It is a reference into the existing
    encrypted secret store, so an API key is handled exactly like a database
    password: encrypted at rest, never returned by the API, and redacted out of
    error messages.
    """

    __tablename__ = "ai_provider"

    id: Mapped[int] = mapped_column(primary_key=True)
    # ollama | anthropic | openai-compatible
    kind: Mapped[str] = mapped_column(String(32), default="ollama")
    base_url: Mapped[str] = mapped_column(String(512), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    secret_name: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120)
    updated_by: Mapped[str | None] = mapped_column(String(64))

    # How the credential is presented. Providers disagree: Anthropic wants
    # x-api-key, OpenAI-compatible servers want a bearer token, Azure wants
    # api-key, and some gateways sit behind basic auth. Rather than hard-code a
    # rule per provider and be wrong for the next one, the method is a setting.
    # none | bearer | header | basic
    auth_method: Mapped[str] = mapped_column(String(16), default="none")
    # The header name when auth_method is "header".
    auth_header: Mapped[str] = mapped_column(String(64), default="")
    # The user half of basic auth; the password half is the referenced secret.
    auth_username: Mapped[str] = mapped_column(String(128), default="")
    # Anything else the endpoint insists on -- an API version, a project or
    # organisation id, a gateway's routing header. JSON object of header -> value.
    extra_headers: Mapped[str] = mapped_column(Text, default="{}")
    # Generation settings, kept here so every feature behaves consistently.
    temperature: Mapped[str] = mapped_column(String(16), default="0")
    max_tokens: Mapped[int] = mapped_column(Integer, default=1500)


class SchemaRegistry(Base, TimestampMixin):
    """The Confluent Schema Registry, if there is one.

    One row, and entirely optional: without it nothing about Avro appears in the
    console, which is correct for the many installations that never touch it. The
    credential is a reference into the secret store, exactly as the AI provider's
    is -- one mechanism for credentials, not three.
    """

    __tablename__ = "schema_registry"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(512), default="")
    # none | basic | bearer
    auth_method: Mapped[str] = mapped_column(String(16), default="none")
    username: Mapped[str] = mapped_column(String(128), default="")
    secret_name: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10)
    updated_by: Mapped[str | None] = mapped_column(String(64))


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
    version: Mapped[int] = mapped_column(Integer, default=1)

    versions: Mapped[list["CatalogVersion"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan",
        order_by="CatalogVersion.version.desc()",
    )

    __table_args__ = (UniqueConstraint("name", name="uq_catalog_name"),)


class CatalogVersion(Base):
    """One past definition of a source or sink.

    Jobs were versioned from the start and catalog entries were not, which had it
    backwards: one entry feeds many jobs, so changing a source's consumer group or
    its columns silently changes behaviour for everything referencing it. That is
    the edit most worth being able to look back at, and it was the one with no
    history at all.
    """

    __tablename__ = "catalog_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_entries.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    sql_text: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(String(512))
    options_json: Mapped[str] = mapped_column(Text, default="{}")
    note: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(64))

    entry: Mapped[CatalogEntry] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint("entry_id", "version", name="uq_catalog_entry_version"),
    )


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

    @property
    def latest_savepoint(self) -> str | None:
        """The most recent state saved for this job, if any.

        Runs come back newest first, so the first one carrying a path is the most
        recent. Lives here rather than in a route because the scheduler needs the
        same answer, and a service importing a route module to get it would be
        the wrong way round.
        """
        for run in self.runs:
            if run.savepoint_path:
                return run.savepoint_path
        return None

    @property
    def restore_point(self) -> "RestorePoint | None":
        """The newest state this job can resume from: a savepoint or a checkpoint.

        Savepoints exist only when someone stops a job on purpose, so after a crash
        the newest one can be days old. Resuming from it rewinds the job and
        replays everything since, which a Kafka sink writes a second time. The
        checkpoint recorded while the run was alive is at most one interval old.

        A checkpoint that a later run restored from and then failed without
        completing a checkpoint of its own is skipped. Flink deletes superseded
        checkpoints, so the recorded path can be gone by the time it is needed;
        retrying it forever would keep the job down, while falling back to a
        savepoint only costs a replay.
        """
        failed_restores = {
            run.restored_from
            for run in self.runs
            if run.restored_from
            and run.state == RunState.FAILED.value
            and not run.checkpoint_path
            and not run.savepoint_path
        }
        points: list[RestorePoint] = []
        for run in self.runs:
            if run.savepoint_path:
                points.append(RestorePoint(
                    run.savepoint_path, "savepoint", _aware(run.ended_at or run.started_at)
                ))
            if run.checkpoint_path and run.checkpoint_path not in failed_restores:
                points.append(RestorePoint(
                    run.checkpoint_path, "checkpoint", _aware(run.checkpoint_at or run.started_at)
                ))
        if not points:
            return None
        # Runs come back newest first, so on a tie the more recent run wins.
        return max(points, key=lambda p: p.taken_at)

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
    # Where this run's state was written when it was stopped with a savepoint.
    # A stateful job resumed without one restarts from committed offsets with an
    # empty state: a half-finished session window, a running count, a join buffer
    # are all simply gone. This is what makes a restart safe.
    savepoint_path: Mapped[str | None] = mapped_column(String(1024))
    # The newest checkpoint Flink completed for this run, recorded on every
    # reconcile while the cluster still knows the job. Flink forgets a job when
    # its JobManager restarts without HA, and with it the only record of where
    # the checkpoint was written, so the path has to be captured beforehand.
    checkpoint_path: Mapped[str | None] = mapped_column(String(1024))
    checkpoint_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The savepoint or checkpoint this run started from, if any.
    restored_from: Mapped[str | None] = mapped_column(String(1024))
    # Set when someone decides a failure has been dealt with. Recorded rather than
    # hidden in a browser, so it means the same thing to everyone looking.
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(64))
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
