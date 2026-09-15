"""Alembic environment.

The database URL comes from MARS's own settings rather than alembic.ini, so a
deployment configures one thing and migrations follow it.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db import Base
from app.settings import settings
import app.models  # noqa: F401  (imported for its side effect of registering tables)

config = context.config
# Only when alembic is driven from the command line. Run in-process at startup it
# must not touch logging at all: the ini sets the root logger to WARN, which threw
# away every INFO line the console emits -- including the connector list and,
# because migrations only run on a first install, the generated administrator
# password. The console configures its own logging and is the owner of it.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    # disable_existing_loggers defaults to True, which silences every logger
    # configured before this point -- including uvicorn's and the application's.
    #
    # That is worse than it sounds. Migrations only actually run on a first
    # install or an upgrade (upgrade_to_head returns early when the schema is
    # already current), so logging died on exactly the run that prints the
    # generated administrator password, and nowhere else. A fresh install
    # therefore came up working but silent, and the README's
    # "docker logs | grep administrator" found nothing, with no way in.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", settings().resolved_database_url())
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER most things in place; batch mode rewrites the table.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
