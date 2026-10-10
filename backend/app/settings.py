"""Configuration for the MARS console.

Every value has a working default so ``docker compose up`` needs no .env at all.
Anything security-sensitive is generated on first run rather than shipped with a
default, so no two installs share a secret.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MARS_", env_file=".env", extra="ignore")

    # --- Flink ---
    # Examples are seeded once, when the first administrator is created. Set this
    # false for an install that should come up empty.
    seed_examples: bool = True
    examples_dir: Path = Path("/app/examples")

    flink_rest_url: str = "http://jobmanager:8081"
    # The address to put in links to Flink's own UI, for deployments where the
    # browser cannot use flink_rest_url -- behind a reverse proxy, or with the UI
    # port remapped. Left empty, the console derives it from its own URL, which is
    # right for the stock compose file.
    flink_ui_url: str = ""
    sql_gateway_url: str = "http://sql-gateway:8083"

    # --- storage ---
    # SQLite by default so a fresh deploy needs no database container. Point
    # DATABASE_URL at Postgres for anything with more than one operator.
    data_dir: Path = Path("/data")
    database_url: str = ""

    # --- security ---
    # Both are generated into the data dir on first start if absent.
    secret_key_file: str = "secret.key"
    session_cookie: str = "mars_session"
    session_cookie_secure: bool = False
    session_ttl_hours: int = 12

    # --- connector registry ---
    # Scanned for mars-manifest.json inside connector JARs.
    connector_lib_dir: Path = Path("/opt/flink/lib")
    manifest_dir: Path = Path("/data/manifests")

    # --- behaviour ---
    job_poll_seconds: int = 10
    request_timeout_seconds: int = 30

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'mars.db'}"


@lru_cache
def settings() -> Settings:
    return Settings()
