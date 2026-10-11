"""Resolving which cluster a job runs on.

A job names a target, or names none and gets the default. This module turns that
name into the pair of clients that talk to that cluster, and caches them so a
submission is not rebuilding HTTP clients every time.

Everything downstream already took its gateway and cluster as arguments, so adding
targets meant replacing one hard-coded pair with a lookup rather than threading a
new concept through the call graph.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .cluster import FlinkClusterClient
from .gateway import SqlGatewayClient
from .models import Job, Target
from .secrets import SecretStore
from .settings import settings
from .submitter import JobSubmitter

log = logging.getLogger(__name__)

DEFAULT_TARGET = "default"


class UnknownTargetError(RuntimeError):
    pass


class TargetRegistry:
    """Caches one submitter per target."""

    def __init__(self, store: SecretStore) -> None:
        self._store = store
        self._submitters: dict[str, JobSubmitter] = {}
        self._urls: dict[str, tuple[str, str]] = {}

    def ensure_default(self, db: Session) -> Target:
        """Creates the default target on first start, from configuration.

        Without this an upgrade would leave every job pointing at a target that does
        not exist. The URLs come from the same settings the single-cluster build
        used, so an existing deployment keeps working untouched.
        """
        existing = db.scalar(select(Target).where(Target.is_default.is_(True)))
        if existing is not None:
            return existing

        s = settings()
        target = db.scalar(select(Target).where(Target.name == DEFAULT_TARGET))
        if target is None:
            target = Target(
                name=DEFAULT_TARGET,
                description="The cluster MARS was configured with.",
                flink_rest_url=s.flink_rest_url,
                gateway_url=s.sql_gateway_url,
                ui_url=s.flink_ui_url or None,
            )
            db.add(target)
        target.is_default = True
        db.flush()
        log.info("Default execution target is '%s' (%s)", target.name, target.flink_rest_url)
        return target

    def resolve(self, db: Session, name: str | None) -> Target:
        """Finds a target by name, falling back to the default."""
        if name:
            target = db.scalar(select(Target).where(Target.name == name))
            if target is None:
                raise UnknownTargetError(
                    f"No execution target named '{name}'. It may have been renamed or "
                    f"removed; pick another under Cluster."
                )
            if not target.enabled:
                raise UnknownTargetError(
                    f"Execution target '{name}' is disabled, so jobs cannot be sent to it."
                )
            return target
        return self.ensure_default(db)

    def for_job(self, db: Session, job: Job) -> Target:
        return self.resolve(db, job.target_name)

    def submitter(self, target: Target) -> JobSubmitter:
        urls = (target.flink_rest_url, target.gateway_url)
        # Rebuild if the target was edited, so a corrected URL takes effect without
        # restarting the console.
        if self._urls.get(target.name) != urls:
            self._submitters.pop(target.name, None)
            self._urls[target.name] = urls

        if target.name not in self._submitters:
            s = settings()
            self._submitters[target.name] = JobSubmitter(
                SqlGatewayClient(target.gateway_url, timeout=s.request_timeout_seconds),
                FlinkClusterClient(target.flink_rest_url),
                self._store,
            )
        return self._submitters[target.name]

    def cluster(self, target: Target) -> FlinkClusterClient:
        return FlinkClusterClient(target.flink_rest_url)

    def for_job_submitter(self, db: Session, job: Job) -> JobSubmitter:
        return self.submitter(self.for_job(db, job))

    def gateway(self, target: Target, timeout: float = 90.0) -> SqlGatewayClient:
        """A gateway client of its own, for work that waits on a whole job."""
        return SqlGatewayClient(target.gateway_url, timeout=timeout)

    def all_enabled(self, db: Session) -> list[Target]:
        return list(db.scalars(select(Target).where(Target.enabled.is_(True)).order_by(Target.name)))

    def forget(self, name: str) -> None:
        self._submitters.pop(name, None)
        self._urls.pop(name, None)


def labels_of(target: Target) -> dict[str, str]:
    try:
        v = json.loads(target.labels or "{}")
        return {str(k): str(x) for k, x in v.items()} if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}
