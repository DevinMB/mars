from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Settings are read at import time, so point them at a temp dir before app imports.
_TMP = tempfile.mkdtemp(prefix="mars-test-")
os.environ.setdefault("MARS_DATA_DIR", _TMP)
os.environ.setdefault("MARS_DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app import models  # noqa: F401  (registers tables on Base)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path
