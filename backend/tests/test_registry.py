"""The registry is the mechanism that lets a connector appear in the console
without the console knowing anything about it. These tests guard that contract."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from app.registry import ConnectorRegistry, Connector


def _jar(tmp_path: Path, name: str, manifest: dict | None) -> Path:
    jar = tmp_path / name
    with zipfile.ZipFile(jar, "w") as z:
        z.writestr("dummy.class", b"\x00")
        if manifest is not None:
            z.writestr("mars-manifest.json", json.dumps(manifest))
    return jar


def _manifest(identifier: str, **over) -> dict:
    base = {
        "manifestVersion": 1,
        "connector": identifier,
        "displayName": identifier.title(),
        "kinds": ["sink"],
        "options": [
            {"key": "url", "label": "URL", "type": "string", "required": True, "secret": False},
            {"key": "password", "label": "Password", "type": "password", "required": False, "secret": True},
        ],
        "columns": [{"name": "doc", "sqlType": "STRING", "required": True}],
    }
    base.update(over)
    return base


def test_discovers_manifest_inside_jar(tmp_path: Path) -> None:
    jars = tmp_path / "jars"
    jars.mkdir()
    _jar(jars, "thing.jar", _manifest("thing"))

    reg = ConnectorRegistry(bundled_dir=tmp_path / "none", jar_dir=jars)
    reg.load()

    c = reg.get("thing")
    assert c is not None
    assert c.display_name == "Thing"
    assert c.source == "jar:thing.jar"
    assert c.secret_keys() == {"password"}


def test_jar_manifest_overrides_bundled(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "thing.json").write_text(json.dumps(_manifest("thing", displayName="Old")))

    jars = tmp_path / "jars"
    jars.mkdir()
    _jar(jars, "thing.jar", _manifest("thing", displayName="New"))

    reg = ConnectorRegistry(bundled_dir=bundled, jar_dir=jars)
    reg.load()

    # Shipping a newer connector JAR must also update its form.
    assert reg.get("thing").display_name == "New"


def test_jar_without_manifest_is_ignored(tmp_path: Path) -> None:
    jars = tmp_path / "jars"
    jars.mkdir()
    _jar(jars, "plain.jar", None)

    reg = ConnectorRegistry(bundled_dir=tmp_path / "none", jar_dir=jars)
    reg.load()
    assert reg.all() == []


def test_corrupt_jar_does_not_break_startup(tmp_path: Path) -> None:
    jars = tmp_path / "jars"
    jars.mkdir()
    (jars / "broken.jar").write_bytes(b"not a zip file at all")
    _jar(jars, "good.jar", _manifest("good"))

    reg = ConnectorRegistry(bundled_dir=tmp_path / "none", jar_dir=jars)
    reg.load()

    # One bad artifact must not take the console down with it.
    assert [c.connector for c in reg.all()] == ["good"]


def test_future_manifest_version_is_rejected_clearly() -> None:
    with pytest.raises(ValueError, match="newer than this console understands"):
        Connector.from_json(_manifest("x", manifestVersion=99), source="test")


def test_kinds_filter_separates_sources_and_sinks(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "a.json").write_text(json.dumps(_manifest("a", kinds=["source"])))
    (bundled / "b.json").write_text(json.dumps(_manifest("b", kinds=["source", "sink"])))

    reg = ConnectorRegistry(bundled_dir=bundled, jar_dir=tmp_path / "none")
    reg.load()

    assert [c.connector for c in reg.for_kind("source")] == ["a", "b"]
    assert [c.connector for c in reg.for_kind("sink")] == ["b"]


def test_shipped_manifests_are_valid() -> None:
    """The manifests MARS bundles must themselves parse, or a fresh install has no
    way to create a Kafka source."""
    bundled = Path(__file__).resolve().parents[1] / "manifests"
    reg = ConnectorRegistry(bundled_dir=bundled, jar_dir=bundled / "nope")
    reg.load()

    names = {c.connector for c in reg.all()}
    assert {"kafka", "datagen", "print", "filesystem"} <= names

    kafka = reg.get("kafka")
    assert "source" in kafka.kinds and "sink" in kafka.kinds
    assert kafka.option("properties.bootstrap.servers").required

    # Conditional fields must point at options that exist, or they can never show.
    for c in reg.all():
        keys = {o.key for o in c.options}
        for o in c.options:
            if o.visible_when:
                assert o.visible_when["option"] in keys, (
                    f"{c.connector}.{o.key} depends on unknown option "
                    f"{o.visible_when['option']}"
                )
