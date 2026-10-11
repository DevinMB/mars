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
    # The Flink image the default cluster runs, passed in by compose. Shown when
    # adding a cluster, so a new one runs exactly the same image and connectors.
    flink_image: str = ""

    # --- versions and updates ---
    # Stamped into the console image by the release build.
    revision: str = ""
    built_at: str = ""
    # The images this installation runs, passed in by compose.
    console_image: str = ""
    # The commit the Flink image was built from, when the deployment records it.
    flink_revision: str = ""
    # Asking GitHub what's newest is an outbound request, so it is off by default.
    update_check: bool = False
    update_channel: str = "releases"  # "releases" (tagged versions) or "main"
    update_repo: str = "DevinMB/mars"
    # A MARS secret holding a read-only GitHub token, for a private repository.
    update_token_secret: str = ""
    # How this installation updates, e.g. "deploy.sh {component} {commit}". Empty
    # gives generic Docker Compose steps.
    update_instructions: str = ""

    # --- restore drill (off unless enabled) ---
    # A scheduled check that backups can actually be restored. See restore_drill.py.
    restore_drill: bool = False
    restore_drill_schedule: str = "0 6 1 1,4,7,10 *"  # quarterly, 06:00 UTC
    # Where backup archives are mounted. Empty or missing: test a fresh snapshot.
    restore_drill_backups_dir: str = "/backups"
    # Flink's state volume, mounted read-only, to check restore points exist.
    flink_state_dir: str = "/flink-state"

    # --- savepoint retention ---
    # Neither Flink nor MARS deleted old savepoints, so they piled up for good.
    # The newest this many per job are kept, plus anything a job would resume
    # from; older ones are removed through Flink. 0 keeps every savepoint.
    savepoints_keep: int = 3

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
