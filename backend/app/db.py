"""Database engine and session handling.

SQLite by default so a fresh ``docker compose up`` needs no database container.
Set ``MARS_DATABASE_URL`` to a Postgres DSN for installs with more than one
operator; the models are deliberately portable between the two.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import settings


class Base(DeclarativeBase):
    pass


def _build_engine() -> Engine:
    url = settings().resolved_database_url()
    if url.startswith("sqlite"):
        settings().data_dir.mkdir(parents=True, exist_ok=True)
        eng = create_engine(
            url,
            # How long a write waits for the lock. The wait blocks the thread, and
            # for code on the event loop that is the whole console, so it is kept
            # short: writes here take milliseconds, and none is held open across
            # a network call (see JobSubmitter._submit).
            connect_args={"check_same_thread": False, "timeout": 5},
            pool_pre_ping=True,
        )

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            # WAL lets the scheduler write run history while a request reads, which
            # is otherwise the classic "database is locked" failure under SQLite.
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        return eng

    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for work outside a request, such as the scheduler."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
