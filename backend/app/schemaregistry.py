"""The Confluent Schema Registry, and turning an Avro schema into columns.

Avro is stricter than JSON in a way that matters here. With JSON a source can be
sampled and its fields inferred, and a field nobody declared is simply ignored.
With Avro the column list *is* the contract: Flink derives the record schema from
the declared columns, and a mismatch is a runtime failure rather than a missing
value. So the question "what columns should I write?" has exactly one right
answer, and it is not one anybody should be typing from memory.

The registry already holds that answer. Given a subject, this reads the schema and
produces the column list, which is better than sampling could ever be: it is the
schema rather than an inference from a handful of records.

Optional throughout. No registry configured means none of this appears, and a
topic that is not Avro never goes near it.
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)

TIMEOUT = 10.0

AUTH_NONE = "none"
AUTH_BASIC = "basic"
AUTH_BEARER = "bearer"
AUTH_METHODS = (AUTH_NONE, AUTH_BASIC, AUTH_BEARER)


class RegistryError(RuntimeError):
    """Something went wrong talking to the registry. The message is user-facing."""


@dataclass
class RegistryConfig:
    url: str = ""
    auth_method: str = AUTH_NONE
    username: str = ""
    credential: str | None = None
    timeout_seconds: int = 10

    @property
    def configured(self) -> bool:
        if not self.url:
            return False
        if self.auth_method in (AUTH_BASIC, AUTH_BEARER) and not self.credential:
            return False
        return True

    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.schemaregistry.v1+json, application/json"}
        if self.auth_method == AUTH_BASIC and self.credential:
            token = base64.b64encode(
                f"{self.username}:{self.credential}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {token}"
        elif self.auth_method == AUTH_BEARER and self.credential:
            headers["Authorization"] = f"Bearer {self.credential}"
        return headers


@dataclass
class Column:
    name: str
    sql_type: str
    # Why this type, in the schema's own terms, so a surprising mapping can be
    # checked rather than argued with.
    note: str = ""


@dataclass
class SchemaResult:
    subject: str = ""
    version: int | None = None
    schema_id: int | None = None
    columns: list[Column] = field(default_factory=list)
    # Parts of the schema that have no clean SQL equivalent.
    warnings: list[str] = field(default_factory=list)
    raw: str = ""


# Avro's primitives, and what Flink calls them.
_PRIMITIVE = {
    "string": "STRING",
    "bytes": "BYTES",
    "int": "INT",
    "long": "BIGINT",
    "float": "FLOAT",
    "double": "DOUBLE",
    "boolean": "BOOLEAN",
    "null": "STRING",
}

# Logical types ride on a primitive and change what it means. Ignoring them is
# how a timestamp arrives as a meaningless bigint.
_LOGICAL = {
    "date": "DATE",
    "time-millis": "TIME(3)",
    "time-micros": "TIME(6)",
    "timestamp-millis": "TIMESTAMP(3)",
    "timestamp-micros": "TIMESTAMP(6)",
    "local-timestamp-millis": "TIMESTAMP_LTZ(3)",
    "local-timestamp-micros": "TIMESTAMP_LTZ(6)",
    "uuid": "STRING",
}


def avro_to_sql(node: Any, warnings: list[str], path: str = "") -> str:
    """One Avro type as one Flink SQL type."""
    if isinstance(node, str):
        return _PRIMITIVE.get(node, "STRING")

    if isinstance(node, list):
        # A union. The overwhelmingly common shape is ["null", X], which is just
        # a nullable X -- every Flink column is nullable already.
        non_null = [n for n in node if n != "null"]
        if len(non_null) == 1:
            return avro_to_sql(non_null[0], warnings, path)
        if not non_null:
            return "STRING"
        warnings.append(
            f"{path or 'a field'} is a union of several types "
            f"({', '.join(str(n) if isinstance(n, str) else n.get('type', '?') for n in non_null)}); "
            f"Flink has no equivalent, so it is mapped to STRING."
        )
        return "STRING"

    if not isinstance(node, dict):
        return "STRING"

    logical = node.get("logicalType")
    if logical == "decimal":
        precision = int(node.get("precision", 38))
        scale = int(node.get("scale", 0))
        return f"DECIMAL({precision}, {scale})"
    if logical in _LOGICAL:
        return _LOGICAL[logical]

    kind = node.get("type")
    if isinstance(kind, (list, dict)):
        return avro_to_sql(kind, warnings, path)

    if kind == "record":
        parts = []
        for f in node.get("fields", []):
            child = f.get("name")
            where = f"{path}.{child}" if path else str(child)
            parts.append(f"`{child}` {avro_to_sql(f.get('type'), warnings, where)}")
        return f"ROW<{', '.join(parts)}>" if parts else "STRING"
    if kind == "array":
        return f"ARRAY<{avro_to_sql(node.get('items'), warnings, path)}>"
    if kind == "map":
        return f"MAP<STRING, {avro_to_sql(node.get('values'), warnings, path)}>"
    if kind == "enum":
        return "STRING"
    if kind == "fixed":
        return "BYTES"

    return _PRIMITIVE.get(kind, "STRING")


def columns_from_schema(schema_text: str) -> tuple[list[Column], list[str]]:
    """The column list a table should declare for this schema."""
    warnings: list[str] = []
    try:
        schema = json.loads(schema_text)
    except (TypeError, ValueError) as exc:
        raise RegistryError(f"The registry returned something that is not a schema: {exc}")

    if not isinstance(schema, dict) or schema.get("type") != "record":
        raise RegistryError(
            "This subject's schema is not an Avro record, so it does not describe "
            "a set of columns. Only record schemas map onto a table."
        )

    columns: list[Column] = []
    for f in schema.get("fields", []):
        name = f.get("name")
        if not name:
            continue
        sql = avro_to_sql(f.get("type"), warnings, name)
        note = ""
        raw_type = f.get("type")
        if isinstance(raw_type, list) and "null" in raw_type:
            note = "optional in the schema"
        elif isinstance(raw_type, dict) and raw_type.get("logicalType"):
            note = f"{raw_type['logicalType']} in the schema"
        columns.append(Column(name=name, sql_type=sql, note=note))

    if not columns:
        warnings.append("The schema is a record with no fields.")
    return columns, warnings


class RegistryClient:
    def __init__(self, config: RegistryConfig) -> None:
        self._c = config

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._c.url.rstrip("/"),
            timeout=self._c.timeout_seconds or TIMEOUT,
            headers=self._c.headers(),
        )

    async def _get(self, path: str) -> Any:
        if not self._c.configured:
            raise RegistryError("No schema registry is configured.")
        try:
            async with self._client() as c:
                r = await c.get(path)
        except httpx.HTTPError as exc:
            raise RegistryError(
                f"Could not reach {self._c.url}. {type(exc).__name__}"
            ) from exc

        if r.status_code in (401, 403):
            raise RegistryError("The registry rejected these credentials.")
        if r.status_code == 404:
            raise RegistryError("The registry has no such subject or version.")
        if r.status_code >= 400:
            raise RegistryError(f"The registry answered {r.status_code}.")
        try:
            return r.json()
        except ValueError as exc:
            raise RegistryError(f"The registry returned unreadable JSON: {exc}") from exc

    async def subjects(self) -> list[str]:
        value = await self._get("/subjects")
        return sorted(str(s) for s in value) if isinstance(value, list) else []

    async def latest(self, subject: str) -> SchemaResult:
        value = await self._get(f"/subjects/{subject}/versions/latest")
        if not isinstance(value, dict):
            raise RegistryError("The registry returned an unexpected shape.")

        # Only Avro maps onto columns this way; Protobuf and JSON Schema are
        # different problems and pretending otherwise produces nonsense.
        schema_type = (value.get("schemaType") or "AVRO").upper()
        if schema_type != "AVRO":
            raise RegistryError(
                f"This subject holds a {schema_type} schema. Only Avro is supported here."
            )

        text = value.get("schema") or ""
        columns, warnings = columns_from_schema(text)
        return SchemaResult(
            subject=subject,
            version=value.get("version"),
            schema_id=value.get("id"),
            columns=columns,
            warnings=warnings,
            raw=text,
        )

    async def check(self) -> tuple[bool, str]:
        """Is it there, and does it look like a schema registry?"""
        try:
            found = await self.subjects()
        except RegistryError as exc:
            return False, str(exc)
        if not found:
            return True, "Reachable, but it has no subjects registered yet."
        return True, f"Reachable, with {len(found)} subject{'' if len(found) == 1 else 's'}."
