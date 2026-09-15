"""Puts something on the screen the first time MARS starts.

A fresh install used to open on an empty Jobs page telling the user to create a
job, which they cannot do until they have created catalog entries -- so the first
thing a new user meets is a dead end.

Seeding happens exactly once, at the moment the first administrator is created,
which is a one-time event by construction. It therefore cannot resurrect examples
somebody deliberately deleted, and needs no extra table to remember that it ran.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from .portability import import_all, parse
from .secrets import SecretStore

log = logging.getLogger(__name__)


def seed_examples(db: Session, store: SecretStore, directory: Path) -> int:
    """Imports every example in a directory. Returns how many things it made."""
    if not directory.is_dir():
        log.info("No examples directory at %s; nothing to seed.", directory)
        return 0

    made = 0
    for path in sorted(directory.glob("*.yaml")):
        try:
            payload = parse(path.read_text())
        except (OSError, ValueError) as exc:
            log.warning("Skipping example %s: %s", path.name, exc)
            continue

        try:
            outcome = import_all(db, store, payload, dry_run=False, replace=False)
        except Exception as exc:
            # An example that fails to import must never stop MARS from starting.
            log.warning("Could not seed %s: %s", path.name, exc)
            continue

        made += len(outcome.created)
        for problem in outcome.errors:
            log.warning("Example %s: %s", path.name, problem)

    if made:
        log.info("Seeded %d example definition(s). Delete them whenever you like.", made)
    return made
