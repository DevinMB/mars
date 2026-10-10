import pytest
from cryptography.fernet import Fernet

from app.models import CatalogEntry, Job
from app.portability import export_all, import_all, parse, to_yaml
from app.secrets import SecretStore


@pytest.mark.parametrize("text", [
    "format: []", "format: true", "catalog: [hello]", "jobs: {}",
    "catalog: [{name: x, sql: [oops]}]", "secrets_required: [{}]",
    "jobs: [{name: x, sql: SELECT 1, uses: source}]",
    "jobs: [{name: x, sql: SELECT 1, enabled: 'false'}]",
    "jobs: [{name: x, sql: SELECT 1, schedule: {mode: cron, cron: bad}}]",
    "jobs: [{name: x, sql: SELECT 1, schedule: {timezone: Invalid/Zone}}]",
    "jobs: [{name: x, sql: SELECT 1}, {name: x, sql: SELECT 2}]",
    "catalog: &loop [*loop]", "!!python/object/apply:os.system ['echo unsafe']",
    "catalog: " + "[" * 50 + "]" * 50,
])
def test_invalid_imports_are_rejected_without_echoing_payload(text):
    with pytest.raises(ValueError):
        parse(text)


def test_size_limit_precedes_yaml_parsing():
    with pytest.raises(ValueError, match="5 MiB"):
        parse("#" * (5 * 1024 * 1024 + 1))


def test_failed_import_is_atomic(db):
    store = SecretStore(key=Fernet.generate_key())
    payload = parse("""
format: 1
catalog:
  - {name: source, kind: source, sql: 'CREATE TABLE source (x INT)'}
jobs:
  - {name: good, sql: 'SELECT * FROM source', uses: [source]}
  - {name: bad, sql: 'SELECT * FROM missing', uses: [missing]}
""")
    result = import_all(db, store, payload, dry_run=False)
    assert not result.ok and not result.created and not result.updated
    assert db.query(CatalogEntry).count() == db.query(Job).count() == 0


def test_unknown_target_does_not_silently_import(db):
    store = SecretStore(key=Fernet.generate_key())
    result = import_all(db, store, {"jobs": [{"name": "example", "sql": "SELECT 1", "target": "absent"}]}, dry_run=False)
    assert not result.ok
    assert db.query(Job).count() == 0


def test_valid_export_round_trips_and_dry_run_does_not_write(db):
    store = SecretStore(key=Fernet.generate_key())
    payload = {"format": 1, "jobs": [{"name": "example", "sql": "SELECT 1", "enabled": False}]}
    assert import_all(db, store, payload).ok
    assert db.query(Job).count() == 0
    assert import_all(db, store, payload, dry_run=False).ok
    exported = parse(to_yaml(export_all(db, store)))
    assert exported["jobs"][0]["enabled"] is False
