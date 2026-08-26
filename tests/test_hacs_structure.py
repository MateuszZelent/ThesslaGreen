from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "thessla_green"


def test_hacs_repository_contains_one_valid_integration() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))

    assert hacs == {"name": "Thessla Green", "content_in_root": False}
    assert sorted(path.name for path in (ROOT / "custom_components").iterdir()) == [
        "thessla_green"
    ]
    assert {
        "domain",
        "name",
        "codeowners",
        "documentation",
        "issue_tracker",
        "version",
    } <= manifest.keys()
    assert manifest["domain"] == "thessla_green"
    assert manifest["config_flow"] is True
    assert manifest["requirements"] == []


def test_home_assistant_adapter_does_not_own_modbus() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in INTEGRATION.glob("*.py")
    )

    assert "pymodbus" not in source
    assert "AsyncModbus" not in source


def test_hacs_exposes_built_in_heater_and_bypass_states_from_one_snapshot() -> None:
    binary_sensor = (INTEGRATION / "binary_sensor.py").read_text(encoding="utf-8")

    assert "ThesslaGreenBypassSensor" in binary_sensor
    assert "ThesslaGreenFpxSensor" in binary_sensor
    assert "ThesslaGreenErvPostHeaterSensor" in binary_sensor
    assert "fpx_stage" in binary_sensor
    assert "erv_post_heater_mode" in binary_sensor


def test_hacs_registers_the_gateway_ui_panel_without_a_second_modbus_owner() -> None:
    panel = INTEGRATION / "www" / "panel.js"
    init_source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")

    assert panel.is_file()
    panel_source = panel.read_text(encoding="utf-8")
    assert "const TAG_NAME = \"thessla-green-panel\"" in panel_source
    assert "customElements.define(TAG_NAME" in panel_source
    assert "gateway_url" in panel_source
    assert "async_register_static_paths" in init_source
    assert "async_register_built_in_panel" in init_source
    assert "pymodbus" not in panel_source


def test_hacs_config_flow_shows_gateway_discovery_evidence() -> None:
    config_flow = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))

    assert "async_get_serial_ports" in config_flow
    assert "async_step_confirm" in config_flow
    assert "serial_ports" in strings["config"]["step"]["confirm"]["description"]
    assert "device_not_found" in strings["config"]["error"]
