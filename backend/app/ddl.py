"""Builds ``CREATE TABLE`` statements from connector manifests and form values.

This is the step that turns a filled-in form into Flink SQL. It is deliberately
one-way: MARS generates the DDL, stores it as text, and from then on the text is
the truth. A user can edit it by hand without MARS fighting them -- the form is a
convenience for getting started, never a cage.

Quoting matters more than it looks. Table and column names go through backticks
and option values through single quotes, and both are validated rather than
trusted, because option values reach here straight from an HTTP request.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .registry import Connector

# Flink identifiers: allow what a sensible table or column is called, and nothing
# that could terminate a quoted identifier.
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,127}$")

# A column type as a user may type it: WORD, WORD(1), WORD(1, 2), ARRAY<...>, etc.
SQL_TYPE = re.compile(r"^[A-Za-z][A-Za-z0-9_ ]*(\([0-9]+(\s*,\s*[0-9]+)?\))?(\s+NOT\s+NULL)?$", re.I)


class DdlError(ValueError):
    pass


@dataclass
class Column:
    name: str
    sql_type: str

    def render(self) -> str:
        if not IDENTIFIER.match(self.name):
            raise DdlError(
                f"'{self.name}' is not a valid column name. Use letters, digits and "
                f"underscores, starting with a letter or underscore."
            )
        sql_type = " ".join(self.sql_type.split())
        if not SQL_TYPE.match(sql_type) and not _is_complex_type(sql_type):
            raise DdlError(f"'{self.sql_type}' is not a recognised column type.")
        return f"  `{self.name}` {sql_type.upper() if len(sql_type) < 40 else sql_type}"


def _is_complex_type(t: str) -> bool:
    """Allows ARRAY<...>, MAP<...>, ROW<...> and MULTISET<...> through unchecked
    except for characters that could break out of the statement."""
    if not re.match(r"^(ARRAY|MAP|ROW|MULTISET)\s*<", t, re.I):
        return False
    return not any(ch in t for ch in ("`", ";", "'", "--", "/*"))


def escape_option_value(value: str) -> str:
    """Escapes a value for a single-quoted Flink SQL string literal."""
    if "\n" in value or "\r" in value:
        raise DdlError("Option values cannot contain newlines.")
    return value.replace("'", "''")


def build_create_table(
    name: str,
    connector: Connector,
    options: dict[str, str],
    columns: list[Column],
    *,
    if_not_exists: bool = True,
) -> str:
    """Renders a CREATE TABLE for one catalog entry.

    ``if_not_exists`` is on by default because catalog fragments are replayed
    ahead of every job submission, and two jobs sharing a source would otherwise
    collide on the second replay within a session.
    """
    if not IDENTIFIER.match(name):
        raise DdlError(
            f"'{name}' is not a valid table name. Use letters, digits and underscores, "
            f"starting with a letter or underscore."
        )
    if not columns:
        raise DdlError("A table needs at least one column.")

    missing = [
        o.key
        for o in connector.options
        if o.required and not str(options.get(o.key, "")).strip()
    ]
    if missing:
        raise DdlError(
            f"{connector.display_name} requires: {', '.join(missing)}."
        )

    unknown = sorted(set(options) - {o.key for o in connector.options} - {"connector"})
    if unknown:
        raise DdlError(
            f"Unknown option(s) for {connector.display_name}: {', '.join(unknown)}."
        )

    rendered_columns = ",\n".join(c.render() for c in columns)

    with_lines = [f"  'connector' = '{escape_option_value(connector.connector)}'"]
    for key in sorted(options):
        raw = options[key]
        if raw is None or str(raw).strip() == "":
            continue
        # An optional value left at its documented default adds noise without
        # changing behaviour. A required one is always emitted: some connectors
        # (Kafka's 'format') declare a default but still reject DDL that omits it.
        spec = connector.option(key)
        if (
            spec is not None
            and not spec.required
            and spec.default is not None
            and str(raw) == spec.default
        ):
            continue
        with_lines.append(f"  '{escape_option_value(key)}' = '{escape_option_value(str(raw))}'")

    exists = "IF NOT EXISTS " if if_not_exists else ""
    return (
        f"CREATE TABLE {exists}`{name}` (\n"
        f"{rendered_columns}\n"
        f") WITH (\n"
        + ",\n".join(with_lines)
        + "\n)"
    )


def columns_for(connector: Connector, overrides: list[dict] | None = None) -> list[Column]:
    """Seeds a column list from the connector's declared contract."""
    if overrides:
        return [Column(name=c["name"], sql_type=c.get("sqlType", "STRING")) for c in overrides]
    return [Column(name=c.name, sql_type=c.sql_type) for c in connector.columns]


def split_statements(script: str) -> list[str]:
    """Splits a SQL script on semicolons that are not inside quotes or comments.

    A naive ``script.split(';')`` breaks on any option value containing one, which
    Kafka JAAS configuration and cron expressions routinely do.
    """
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    in_single = in_double = in_backtick = False
    in_line_comment = in_block_comment = False

    while i < len(script):
        ch = script[i]
        nxt = script[i + 1] if i + 1 < len(script) else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            buf.append(ch)
            i += 1
            continue
        if in_block_comment:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt)
                i += 2
                in_block_comment = False
                continue
            i += 1
            continue

        if not (in_single or in_double or in_backtick):
            if ch == "-" and nxt == "-":
                in_line_comment = True
                buf.append(ch)
                i += 1
                continue
            if ch == "/" and nxt == "*":
                in_block_comment = True
                buf.append(ch)
                i += 1
                continue

        if ch == "'" and not (in_double or in_backtick):
            # '' inside a string is an escaped quote, not a terminator.
            if in_single and nxt == "'":
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
            in_single = not in_single
        elif ch == '"' and not (in_single or in_backtick):
            in_double = not in_double
        elif ch == "`" and not (in_single or in_double):
            in_backtick = not in_backtick
        elif ch == ";" and not (in_single or in_double or in_backtick):
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def options_to_json(options: dict[str, str]) -> str:
    return json.dumps(options, sort_keys=True)


def options_from_json(raw: str) -> dict[str, str]:
    try:
        d = json.loads(raw or "{}")
        return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except json.JSONDecodeError:
        return {}
