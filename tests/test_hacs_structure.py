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
