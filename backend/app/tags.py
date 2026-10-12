"""Tags on jobs: short labels for grouping them by what they do (buoys, sits, ...).

They organise; they change nothing about how a job runs, so editing them does
not make a new job version. One rule for every way in -- the editor, the bulk
action, YAML import -- so a tag means the same thing however it was set.
"""
from __future__ import annotations

import json
import re

TAG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
MAX_TAGS = 10


def clean(tags: list[str] | None) -> list[str]:
    """Lower-cased, trimmed and de-duplicated, in the order given; ValueError
    for anything that is not a tag."""
    out: list[str] = []
    for raw in tags or []:
        if not isinstance(raw, str):
            raise ValueError("Tags must be text.")
        tag = raw.strip().lower()
        if not tag:
            continue
        if not TAG.match(tag):
            raise ValueError(f"'{raw}' is not a valid tag: use up to 32 lowercase letters, "
                             f"digits, '-' or '_', starting with a letter or digit.")
        if tag not in out:
            out.append(tag)
    if len(out) > MAX_TAGS:
        raise ValueError(f"A job can have at most {MAX_TAGS} tags.")
    return out


def of(job) -> list[str]:
    try:
        value = json.loads(job.tags or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return [t for t in value if isinstance(t, str)] if isinstance(value, list) else []


def put(job, tags: list[str]) -> None:
    job.tags = json.dumps(clean(tags))
