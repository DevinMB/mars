"""Bringing the schema up to date on start.

Creating tables from the models is enough for a fresh install and useless for an
upgrade: it adds missing *tables* and never missing *columns*, so a release that
adds a column comes up and then fails at the first query that mentions it. That is
exactly what happened when execution targets added jobs.target_name.

So migrations run on start. The only subtlety is an install that predates this
module: it has tables but no alembic_version, and running the initial migration
against it would try to create tables that already exist. Those are stamped at the
base revision first, then upgraded normally.
"""
from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from .db import engine

log = logging.getLogger(__name__)

# A table from the very first migration. Its presence means the database predates
# migrations rather than being empty.
_SENTINEL_TABLE = "users"


def _config() -> Config:
    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    return cfg


def upgrade_to_head() -> None:
    cfg = _config()
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()

    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
        tables = set(inspect(conn).get_table_names())

    if current is None and _SENTINEL_TABLE in tables:
        # Pre-migration install: adopt it at the base revision so the initial
        # migration is not replayed over existing tables.
        base = script.get_base()
        log.info("Adopting an existing database at revision %s", base)
        command.stamp(cfg, base)
        current = base

    if current == head:
        log.info("Schema is up to date (%s)", head)
        return

    log.info("Upgrading schema %s -> %s", current or "empty", head)
    command.upgrade(cfg, "head")
    log.info("Schema upgraded")
