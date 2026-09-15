"""Connector registry: what MARS knows how to put in a CREATE TABLE.

A connector becomes usable in the console by contributing a manifest describing its
options. Manifests come from two places:

1. **Bundled** JSON under ``manifests/``. Flink's own connectors (Kafka, datagen,
   filesystem, print) ship no manifest of their own, so MARS provides them. Without
   this a fresh install could not create a source at all.
2. **Discovered** from ``mars-manifest.json`` inside any JAR on the connector path.
   This is what lets a third party add a connector to MARS by dropping in a JAR --
   no console code change, no redeploy of anything but Flink.

Discovered manifests win over bundled ones with the same identifier, so shipping a
newer connector JAR also updates its form.
"""
from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MANIFEST_ENTRY = "mars-manifest.json"
SUPPORTED_MANIFEST_VERSION = 1


@dataclass
class ConnectorOption:
    key: str
    label: str
    type: str
    required: bool = False
    secret: bool = False
    group: str = "General"
    default: str | None = None
    placeholder: str | None = None
    help: str | None = None
    choices: list[str] = field(default_factory=list)
    visible_when: dict[str, str] | None = None
    # Other option keys that satisfy this one when it is required. Flink accepts
    # 'format', or 'key.format' plus 'value.format' when the two sides differ;
    # insisting on 'format' alone rejects definitions Flink is perfectly happy
    # with, and made such an entry impossible to save from the form.
    satisfied_by: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "ConnectorOption":
        return cls(
            key=d["key"],
            label=d.get("label") or d["key"],
            type=d.get("type", "string"),
            required=bool(d.get("required", False)),
            secret=bool(d.get("secret", False)),
            group=d.get("group", "General"),
            default=d.get("default"),
            placeholder=d.get("placeholder"),
            help=d.get("help"),
            choices=list(d.get("choices", [])),
            visible_when=d.get("visibleWhen"),
            satisfied_by=list(d.get("satisfiedBy", [])),
        )


@dataclass
class ConnectorColumn:
    name: str
    sql_type: str
    required: bool = False
    help: str | None = None

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "ConnectorColumn":
        return cls(
            name=d["name"],
            sql_type=d.get("sqlType", "STRING"),
            required=bool(d.get("required", False)),
            help=d.get("help"),
        )


@dataclass
class Connector:
    connector: str
    display_name: str
    kinds: list[str]
    description: str | None = None
    docs_url: str | None = None
    supports_health_check: bool = False
    options: list[ConnectorOption] = field(default_factory=list)
    columns: list[ConnectorColumn] = field(default_factory=list)
    source: str = "bundled"

    @classmethod
    def from_json(cls, d: dict[str, Any], source: str) -> "Connector":
        version = d.get("manifestVersion", 1)
        if version > SUPPORTED_MANIFEST_VERSION:
            raise ValueError(
                f"manifest version {version} for '{d.get('connector')}' is newer than "
                f"this console understands ({SUPPORTED_MANIFEST_VERSION}); upgrade MARS"
            )
        return cls(
            connector=d["connector"],
            display_name=d.get("displayName") or d["connector"],
            kinds=list(d.get("kinds", ["sink"])),
            description=d.get("description"),
            docs_url=d.get("docsUrl"),
            supports_health_check=bool(d.get("supportsHealthCheck", False)),
            options=[ConnectorOption.from_json(o) for o in d.get("options", [])],
            columns=[ConnectorColumn.from_json(c) for c in d.get("columns", [])],
            source=source,
        )

    def option(self, key: str) -> ConnectorOption | None:
        return next((o for o in self.options if o.key == key), None)

    def secret_keys(self) -> set[str]:
        return {o.key for o in self.options if o.secret}

    def to_json(self) -> dict[str, Any]:
        return {
            "connector": self.connector,
            "displayName": self.display_name,
            "kinds": self.kinds,
            "description": self.description,
            "docsUrl": self.docs_url,
            "supportsHealthCheck": self.supports_health_check,
            "source": self.source,
            "options": [
                {
                    "key": o.key,
                    "label": o.label,
                    "type": o.type,
                    "required": o.required,
                    "secret": o.secret,
                    "group": o.group,
                    "default": o.default,
                    "placeholder": o.placeholder,
                    "help": o.help,
                    "choices": o.choices,
                    "visibleWhen": o.visible_when,
                    "satisfiedBy": o.satisfied_by,
                }
                for o in self.options
            ],
            "columns": [
                {
                    "name": c.name,
                    "sqlType": c.sql_type,
                    "required": c.required,
                    "help": c.help,
                }
                for c in self.columns
            ],
        }


class ConnectorRegistry:
    """Loads and serves connector manifests."""

    def __init__(self, bundled_dir: Path, jar_dir: Path) -> None:
        self._bundled_dir = bundled_dir
        self._jar_dir = jar_dir
        self._connectors: dict[str, Connector] = {}

    def load(self) -> None:
        found: dict[str, Connector] = {}

        for path in sorted(self._bundled_dir.glob("*.json")) if self._bundled_dir.is_dir() else []:
            try:
                data = json.loads(path.read_text())
                c = Connector.from_json(data, source="bundled")
                found[c.connector] = c
            except Exception as exc:
                log.error("Ignoring bundled manifest %s: %s", path.name, exc)

        for jar in sorted(self._jar_dir.glob("*.jar")) if self._jar_dir.is_dir() else []:
            manifest = _read_manifest_from_jar(jar)
            if manifest is None:
                continue
            try:
                c = Connector.from_json(manifest, source=f"jar:{jar.name}")
                # A shipped JAR is more current than whatever MARS bundled.
                found[c.connector] = c
            except Exception as exc:
                log.error("Ignoring manifest in %s: %s", jar.name, exc)

        self._connectors = found
        log.info(
            "Connector registry loaded: %d connector(s): %s",
            len(found),
            ", ".join(sorted(found)) or "none",
        )

    def all(self) -> list[Connector]:
        return sorted(self._connectors.values(), key=lambda c: c.display_name.lower())

    def for_kind(self, kind: str) -> list[Connector]:
        return [c for c in self.all() if kind in c.kinds]

    def get(self, identifier: str) -> Connector | None:
        return self._connectors.get(identifier)


def _read_manifest_from_jar(jar: Path) -> dict[str, Any] | None:
    try:
        with zipfile.ZipFile(jar) as z:
            if MANIFEST_ENTRY not in z.namelist():
                return None
            return json.loads(z.read(MANIFEST_ENTRY))
    except (zipfile.BadZipFile, OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read %s from %s: %s", MANIFEST_ENTRY, jar.name, exc)
        return None
