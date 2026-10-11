"""The compose file the console hands out for a cluster on another machine.

It has to work when pasted onto a bare machine with nothing else copied, run the
same image as this installation, and refuse to start bound to localhost, where the
console could never reach it.
"""
from __future__ import annotations

import yaml

from app.cluster_setup import TEMPLATE_DIR, render_remote_compose

IMAGE = "ghcr.io/devinmb/mars-flink@sha256:" + "a" * 64


def _rendered() -> dict:
    text = render_remote_compose(IMAGE)
    assert text.startswith("# A MARS cluster for another machine")
    return yaml.safe_load(text)


def test_template_is_found_from_a_checkout():
    assert (TEMPLATE_DIR / "docker-compose.yml").is_file()
    assert (TEMPLATE_DIR / "conf" / "config.yaml").is_file()


def test_every_service_runs_the_pinned_image():
    services = _rendered()["services"]
    assert set(services) == {"jobmanager", "taskmanager", "sql-gateway"}
    assert {s["image"] for s in services.values()} == {IMAGE}


def test_config_is_inlined_rather_than_bind_mounted():
    compose = _rendered()
    original = (TEMPLATE_DIR / "conf" / "config.yaml").read_text()
    assert compose["configs"]["flink-config"]["content"] == original
    for service in compose["services"].values():
        assert not any("./conf/" in str(m) for m in service.get("volumes", []))
        assert service["configs"] == [
            {"source": "flink-config", "target": "/opt/flink/conf/config.yaml"}
        ]


def test_state_volume_is_kept():
    services = _rendered()["services"]
    assert "flink-state:/flink-state" in services["jobmanager"]["volumes"]
    assert "flink-state:/flink-state" in services["taskmanager"]["volumes"]


def test_published_ports_require_an_explicit_bind_address():
    services = _rendered()["services"]
    ports = services["jobmanager"]["ports"] + services["sql-gateway"]["ports"]
    assert ports and all("TARGET_BIND_ADDRESS:?" in p for p in ports)
    assert not any("127.0.0.1" in p for p in ports)


def test_job_submission_stays_disabled_in_the_inlined_config():
    config = yaml.safe_load(_rendered()["configs"]["flink-config"]["content"])
    assert config["web"]["submit"]["enable"] is False
    assert config["web"]["cancel"]["enable"] is False


def test_slot_count_is_set_in_the_inlined_config():
    config = yaml.safe_load(yaml.safe_load(render_remote_compose(IMAGE, slots=12))["configs"]["flink-config"]["content"])
    assert config["taskmanager"]["numberOfTaskSlots"] == 12


def test_default_keeps_the_template_untouched():
    content = _rendered()["configs"]["flink-config"]["content"]
    assert content == (TEMPLATE_DIR / "conf" / "config.yaml").read_text()
