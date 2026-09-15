"""Turns Flink's SQL errors into something a person can act on.

Flink reports faults in the vocabulary of its planner. "Non-query expression
encountered in illegal context" is a typo; "doesn't support consuming update
changes which is produced by node GroupAggregate" is an aggregate feeding an
append-only sink. Both are perfectly precise and neither tells the person who
wrote the statement what to change.

Every pattern here was taken from a real failure produced against this Flink
version rather than written from memory -- the wording differs between releases,
and a translation table built from recollection quietly stops matching.

The contract is deliberately narrow: when a message is recognised it is rewritten
and a hint is added; when it is not, the original survives untouched. A
translation layer that swallows messages it does not understand is worse than no
translation layer, because the one error nobody anticipated is the one someone
most needs to read.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field


@dataclass
class Explanation:
    # The original, always kept: a rewritten message can still be the wrong guess.
    original: str
    message: str
    hint: str | None = None
    code: str = "unknown"
    # 1-based, relative to the statement the user wrote.
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    # Names worth offering when something was misspelled.
    suggestions: list[str] = field(default_factory=list)


@dataclass
class Context:
    """What the console knows that Flink does not: the user's own catalog."""

    tables: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)


# "From line 1, column 52 to line 1, column 55: Column 'nope' not found ..."
_POSITION = re.compile(
    r"From line (?P<l1>\d+), column (?P<c1>\d+)"
    r"(?: to line (?P<l2>\d+), column (?P<c2>\d+))?\s*:\s*(?P<msg>.+)"
)
# Calcite's parser reports positions differently again.
_PARSE_AT = re.compile(
    r'Encountered\s+"(?P<tok>[^"]*)"\s+at line (?P<l1>\d+), column (?P<c1>\d+)'
)
_QUERY_SCHEMA = re.compile(r"Query schema:\s*\[(?P<cols>[^\]]*)\]")
_SINK_SCHEMA = re.compile(r"Sink schema:\s*\[(?P<cols>[^\]]*)\]")


def _near(name: str, options: list[str], n: int = 3) -> list[str]:
    """Close spellings only. At a lower cutoff "whispers_ra" also matched
    "whispers_sink", and a suggestion list that includes the wrong answer costs
    more attention than it saves."""
    if not name or not options:
        return []
    return difflib.get_close_matches(name, options, n=n, cutoff=0.7)


def _plain(table: str) -> str:
    """Strips 'default_catalog.default_database.' and backticks from a name."""
    return table.replace("`", "").split(".")[-1]


def _schema_diff(detail: str) -> str | None:
    """Explains a query/sink mismatch by naming the column that differs.

    Flink says only "do not match" and prints both schemas; which column is wrong
    is left to the reader. With two long schemas that is genuinely hard to see.
    """
    q = _QUERY_SCHEMA.search(detail)
    s = _SINK_SCHEMA.search(detail)
    if not q or not s:
        return None

    def parse(raw: str) -> list[tuple[str, str]]:
        out = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            name, _, type_ = part.partition(":")
            out.append((name.strip(), type_.strip()))
        return out

    query, sink = parse(q.group("cols")), parse(s.group("cols"))

    if len(query) != len(sink):
        return (
            f"Your SELECT produces {len(query)} column"
            f"{'' if len(query) == 1 else 's'} but the sink expects {len(sink)}: "
            f"{', '.join(n for n, _ in sink)}."
        )

    for i, ((qn, qt), (sn, st)) in enumerate(zip(query, sink), start=1):
        if qt != st:
            return (
                f"Column {i} of your SELECT is {qt} ({qn}), but the sink's "
                f"'{sn}' column is {st}. Columns are matched by position, not by "
                f"name, so check the order as well as the types."
            )
    return None


def explain(summary: str, detail: str = "", context: Context | None = None) -> Explanation:
    """Rewrites one Flink error. Unrecognised messages pass through unchanged."""
    ctx = context or Context()
    text = f"{summary}\n{detail}"
    ex = Explanation(original=summary, message=summary)

    # Position first: it applies regardless of which message it is.
    for match in _POSITION.finditer(text):
        ex.line = int(match.group("l1"))
        ex.column = int(match.group("c1"))
        ex.end_line = int(match.group("l2")) if match.group("l2") else ex.line
        ex.end_column = int(match.group("c2")) if match.group("c2") else ex.column
        break
    else:
        match = _PARSE_AT.search(text)
        if match:
            ex.line = int(match.group("l1"))
            ex.column = int(match.group("c1"))
            ex.end_line, ex.end_column = ex.line, ex.column

    # -- a table the catalog does not have --------------------------------
    m = re.search(r"Object '(?P<name>[^']+)' not found", summary)
    if not m:
        m = re.search(
            r"Cannot find table '(?P<name>[^']+)' nor as a temporary table", summary
        )
    if m:
        name = _plain(m.group("name"))

        # The table exists, it just was not declared. Telling someone their table
        # does not exist while suggesting its exact name reads like a bug, and it
        # is the single most common mistake: a job sees only the tables it ticks.
        if name in ctx.tables:
            ex.code = "table_not_declared"
            ex.message = (
                f"'{name}' exists in the Catalog, but this job does not use it yet."
            )
            ex.hint = (
                f"Tick '{name}' under 'Tables this job uses'. Its definition is "
                f"replayed before the job runs, and a job can only see the tables it "
                f"declares."
            )
            return ex

        ex.code = "unknown_table"
        ex.suggestions = _near(name, ctx.tables)
        ex.message = f"There is no table called '{name}'."
        ex.hint = (
            f"Did you mean {_or_list(ex.suggestions)}? Remember to tick it under "
            f"'Tables this job uses'."
            if ex.suggestions
            else "Create it in the Catalog first, then tick it under 'Tables this "
                 "job uses'."
        )
        return ex

    # -- a column that does not exist -------------------------------------
    m = re.search(r"Column '(?P<name>[^']+)' not found in any table", summary)
    if m:
        name = m.group("name")
        ex.code = "unknown_column"
        ex.suggestions = _near(name, ctx.columns)
        ex.message = f"No column called '{name}' in the tables this job reads."
        ex.hint = (
            f"Did you mean {_or_list(ex.suggestions)}?"
            if ex.suggestions
            else "Check the column names on the source table in the Catalog."
        )
        return ex

    # -- a function that does not exist -----------------------------------
    m = re.search(r"No match found for function signature (?P<sig>[\w$]+)\(", summary)
    if m:
        ex.code = "unknown_function"
        ex.message = (
            f"There is no function called '{m.group('sig')}' that accepts those "
            f"arguments."
        )
        ex.hint = (
            "Check the spelling, the number of arguments, and their types. Flink's "
            "built-in functions differ from other SQL dialects."
        )
        return ex

    # -- query and sink shapes disagree -----------------------------------
    if "do not match" in summary and "Column types of query result" in summary:
        ex.code = "schema_mismatch"
        diff = _schema_diff(text)
        ex.message = diff or "What your SELECT produces does not fit the sink's columns."
        ex.hint = (
            "The SELECT list must line up with the sink's columns one for one, in "
            "order. Cast where the types differ."
        )
        return ex

    # -- updates into an append-only sink ---------------------------------
    m = re.search(
        r"Table sink '(?P<sink>[^']+)' doesn't support consuming (?P<kind>update|delete)"
        r" changes which is produced by node (?P<node>\w+)",
        summary,
    )
    if m:
        ex.code = "updates_into_append_sink"
        node = m.group("node")
        cause = {
            "GroupAggregate": "a GROUP BY that is not windowed",
            "Rank": "a ranking or de-duplication",
            "Join": "a regular join",
        }.get(node, f"a {node}")
        ex.message = (
            f"This query revises rows it has already emitted ({cause}), and the sink "
            f"'{_plain(m.group('sink'))}' can only append."
        )
        ex.hint = (
            "A plain Kafka topic cannot express an update. Either aggregate over a "
            "window so each row is emitted once and never revised, or write to a sink "
            "that understands updates -- upsert-kafka, or a CouchDB sink with a "
            "deterministic document id."
        )
        return ex

    # -- ORDER BY on a stream ---------------------------------------------
    if "Sort on a non-time-attribute field is not supported" in summary:
        ex.code = "unbounded_sort"
        ex.message = (
            "A streaming query cannot sort by an ordinary column: the input never "
            "ends, so the first row could always still be overtaken."
        )
        ex.hint = (
            "Sort by a time attribute, or drop the ORDER BY. To keep the top few rows "
            "per key, use a windowed ranking instead."
        )
        return ex

    # -- selected but not grouped -----------------------------------------
    m = re.search(r"Expression '(?P<name>[^']+)' is not being grouped", summary)
    if m:
        name = m.group("name")
        ex.code = "not_grouped"
        ex.message = (
            f"'{name}' is in the SELECT list but not in the GROUP BY, so there is "
            f"more than one possible value for it per group."
        )
        ex.hint = (
            f"Add '{name}' to the GROUP BY, or wrap it in an aggregate such as "
            f"MAX({name})."
        )
        return ex

    # -- syntax ------------------------------------------------------------
    if "Non-query expression encountered in illegal context" in summary:
        ex.code = "syntax"
        ex.message = "This statement is not valid SQL."
        ex.hint = (
            "Usually a misspelled keyword or a missing comma just before this point. "
            "Flink cannot say which, because it stopped being able to parse here."
        )
        return ex

    m = re.search(r'SQL parse failed\..*?Encountered\s+"(?P<tok>[^"]*)"', text, re.S)
    if m:
        token = m.group("tok").strip()
        ex.code = "syntax"
        ex.message = (
            f"Unexpected '{token}' -- this statement stops being valid SQL here."
            if token else "This statement is not valid SQL."
        )
        ex.hint = "Check for a misspelled keyword, a missing comma, or an unclosed bracket."
        return ex

    # Recognised nothing: leave the original exactly as it was.
    return ex


def _or_list(names: list[str]) -> str:
    if len(names) == 1:
        return f"'{names[0]}'"
    return ", ".join(f"'{n}'" for n in names[:-1]) + f" or '{names[-1]}'"
