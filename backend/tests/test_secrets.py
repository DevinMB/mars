"""A leaked credential is the worst failure this product can have, so these tests
cover the paths where one could escape: stored SQL, error text, and logs."""
from __future__ import annotations

import stat

import pytest
from cryptography.fernet import Fernet

from app.secrets import (
    MissingSecretError,
    SecretError,
    SecretStore,
    load_or_create_key,
)


@pytest.fixture
def store() -> SecretStore:
    return SecretStore(key=Fernet.generate_key())


def test_round_trip(db, store):
    store.put(db, "couch_pw", "hunter2", description="CouchDB admin")
    db.commit()
    assert store.reveal(db, "couch_pw") == "hunter2"


def test_value_is_encrypted_at_rest(db, store):
    store.put(db, "couch_pw", "hunter2")
    db.commit()

    from app.models import Secret

    row = db.query(Secret).one()
    assert "hunter2" not in row.ciphertext
    assert row.ciphertext != "hunter2"


def test_resolve_substitutes_only_at_submission(db, store):
    store.put(db, "pw", "s3cret")
    store.put(db, "user", "admin")
    db.commit()

    sql = (
        "CREATE TABLE t (doc STRING) WITH ("
        "'connector'='couchdb','username'='${secret:user}','password'='${secret:pw}')"
    )
    resolved = store.resolve(db, sql)

    assert "'password' = 's3cret'".replace(" ", "") in resolved.replace(" ", "")
    assert "admin" in resolved
    # The stored text is untouched: the caller holds the only resolved copy.
    assert "${secret:pw}" in sql


def test_missing_secret_names_what_is_missing(db, store):
    store.put(db, "present", "x")
    db.commit()

    with pytest.raises(MissingSecretError) as exc:
        store.resolve(db, "${secret:present} ${secret:absent} ${secret:alsogone}")

    msg = str(exc.value)
    assert "absent" in msg and "alsogone" in msg
    assert "present" not in msg.split(":")[-1]
    # The message should tell an operator what to do, not just what broke.
    assert "Secrets" in msg


def test_text_without_references_is_returned_unchanged(db, store):
    sql = "SELECT 1"
    assert store.resolve(db, sql) is sql


def test_redact_removes_leaked_values_from_error_text(db, store):
    store.put(db, "couch_pw", "supersecretvalue")
    db.commit()

    trace = (
        "org.apache.flink.table.api.ValidationException: could not connect using "
        "http://admin:supersecretvalue@couchdb:5984/whispers"
    )
    cleaned = store.redact(db, trace)

    assert "supersecretvalue" not in cleaned
    assert "${secret:couch_pw}" in cleaned


def test_redact_ignores_very_short_values(db, store):
    # A two-character secret would match everywhere and mangle unrelated text.
    store.put(db, "tiny", "ab")
    db.commit()
    text = "a table named abc"
    assert store.redact(db, text) == text


def test_put_is_an_upsert(db, store):
    store.put(db, "pw", "first")
    db.commit()
    store.put(db, "pw", "second")
    db.commit()

    from app.models import Secret

    assert db.query(Secret).count() == 1
    assert store.reveal(db, "pw") == "second"


@pytest.mark.parametrize("bad", ["has space", "has'quote", "has$dollar", "a" * 129, ""])
def test_rejects_unsafe_names(db, store, bad):
    # A name containing a quote could break out of the SQL string it lands in.
    with pytest.raises(SecretError):
        store.put(db, bad, "x")


def test_wrong_key_gives_an_actionable_error(db, store):
    store.put(db, "pw", "value")
    db.commit()

    other = SecretStore(key=Fernet.generate_key())
    with pytest.raises(SecretError, match="encryption key was replaced"):
        other.reveal(db, "pw")


def test_key_file_is_created_private(monkeypatch, tmp_path):
    from app import settings as settings_mod

    settings_mod.settings.cache_clear()
    monkeypatch.setenv("MARS_DATA_DIR", str(tmp_path))

    key = load_or_create_key()
    path = tmp_path / "secret.key"

    assert path.exists() and key
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"key file is {oct(mode)}, expected 0600"

    # A second call must reuse the key, not rotate it and orphan every secret.
    assert load_or_create_key() == key
    settings_mod.settings.cache_clear()


def test_referenced_names_finds_all(store):
    text = "${secret:a} and ${secret:b.c-d_e} and ${secret:a}"
    assert store.referenced_names(text) == {"a", "b.c-d_e"}
