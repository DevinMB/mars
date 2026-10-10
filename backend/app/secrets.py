"""Encrypted secret storage and ``${secret:name}`` resolution.

Why this exists: a job's SQL is listed, diffed, shown in an editor and written to
version history. A CouchDB or Kafka password must never be part of that text. So
job SQL carries a reference:

    'password' = '${secret:couchdb_password}'

and the value is substituted only as the statement is handed to the SQL Gateway.
The stored SQL, every version of it, and anything the console renders keep the
placeholder.

Encryption is Fernet (AES-128-CBC with an HMAC) using a key generated into the
data directory on first start. No default key ships with MARS: two installs must
never share one.
"""
from __future__ import annotations

import logging
import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import quote, quote_plus

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from .models import Secret
from .settings import settings

log = logging.getLogger(__name__)

# ${secret:name} -- names are restricted so a reference cannot smuggle in quotes.
SECRET_REF = re.compile(r"\$\{secret:([A-Za-z0-9_.-]{1,128})\}")


class SecretError(RuntimeError):
    pass


class MissingSecretError(SecretError):
    def __init__(self, names: list[str]) -> None:
        self.names = names
        listed = ", ".join(sorted(names))
        plural = "s" if len(names) > 1 else ""
        super().__init__(
            f"Job references undefined secret{plural}: {listed}. "
            f"Add {'them' if len(names) > 1 else 'it'} under Settings -> Secrets."
        )


def _key_path() -> Path:
    return settings().data_dir / settings().secret_key_file


def load_or_create_key() -> bytes:
    """Reads the instance encryption key, generating it on first run.

    The file is written 0600. If it is lost, stored secrets cannot be decrypted --
    they must be re-entered. That is the intended failure mode: a recoverable key
    would mean a key that an attacker with the database can also recover.
    """
    path = _key_path()
    if path.exists():
        key = path.read_bytes().strip()
        if not key:
            raise SecretError(f"Encryption key at {path} is empty; refusing to start")
        return key

    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    # Create with restrictive permissions rather than widening them afterwards,
    # so the key is never briefly world-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    # Logs where the key was written, never the key itself.
    log.warning(  # nosemgrep: python-logger-credential-disclosure
        "Generated a new secret encryption key at %s. Back it up: without it, "
        "stored secrets cannot be recovered.",
        path,
    )
    return key


class SecretStore:
    def __init__(self, key: bytes | None = None) -> None:
        self._fernet = Fernet(key or load_or_create_key())

    # -- storage ------------------------------------------------------------

    def put(
        self,
        db: Session,
        name: str,
        value: str,
        description: str | None = None,
        created_by: str | None = None,
    ) -> Secret:
        if not SECRET_REF.fullmatch("${secret:%s}" % name):
            raise SecretError(
                f"Invalid secret name '{name}'. Use letters, digits, dot, dash "
                f"or underscore, up to 128 characters."
            )
        ciphertext = self._fernet.encrypt(value.encode()).decode()

        existing = db.query(Secret).filter(Secret.name == name).one_or_none()
        if existing:
            existing.ciphertext = ciphertext
            if description is not None:
                existing.description = description
            return existing

        secret = Secret(
            name=name,
            ciphertext=ciphertext,
            description=description,
            created_by=created_by,
        )
        db.add(secret)
        return secret

    def reveal(self, db: Session, name: str) -> str:
        row = db.query(Secret).filter(Secret.name == name).one_or_none()
        if row is None:
            raise MissingSecretError([name])
        return self._decrypt(row)

    def delete(self, db: Session, name: str) -> bool:
        row = db.query(Secret).filter(Secret.name == name).one_or_none()
        if row is None:
            return False
        db.delete(row)
        return True

    def names(self, db: Session) -> list[str]:
        return [n for (n,) in db.query(Secret.name).order_by(Secret.name).all()]

    # -- resolution ---------------------------------------------------------

    def referenced_names(self, text: str) -> set[str]:
        return set(SECRET_REF.findall(text or ""))

    def resolve(self, db: Session, text: str) -> str:
        """Substitutes every ``${secret:name}`` with its plaintext.

        Call this at the last possible moment -- the result must never be stored,
        logged, or returned to a client.
        """
        wanted = self.referenced_names(text)
        if not wanted:
            return text

        rows = db.query(Secret).filter(Secret.name.in_(wanted)).all()
        found = {r.name: self._decrypt(r) for r in rows}

        missing = sorted(wanted - found.keys())
        if missing:
            raise MissingSecretError(missing)

        return SECRET_REF.sub(lambda m: found[m.group(1)], text)

    def redact(self, db: Session, text: str) -> str:
        """Replaces any literal secret value in text with its placeholder.

        Used on error messages and logs: a Flink stack trace can echo a table
        option back, and a connection string is exactly the kind of thing that
        ends up in one.
        """
        if not text:
            return text
        replacements = {}
        for row in db.query(Secret).all():
            try:
                value = self._decrypt(row)
            except SecretError:
                continue
            # A value this short would match inside unrelated words and mangle them.
            if value and len(value) >= 4:
                # Errors can quote SQL literals or URL/JSON-encode credentials.
                for form in (value, value.replace("'", "''"), quote(value, safe=""),
                             quote_plus(value, safe=""), json.dumps(value)[1:-1]):
                    replacements.setdefault(form, "${secret:%s}" % row.name)
        if not replacements:
            return text
        # Match longest first, in one pass: a short value must not leave the tail
        # of a longer credential visible or rewrite a placeholder we just made.
        pattern = "|".join(re.escape(value) for value in sorted(replacements, key=len, reverse=True))
        return re.sub(pattern, lambda match: replacements[match.group()], text)

    def _decrypt(self, row: Secret) -> str:
        try:
            return self._fernet.decrypt(row.ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise SecretError(
                f"Secret '{row.name}' could not be decrypted. This usually means the "
                f"encryption key was replaced; re-enter the secret."
            ) from exc
