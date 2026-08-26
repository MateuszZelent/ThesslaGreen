from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "thessla_green"


def test_hacs_repository_contains_one_valid_integration() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))

    assert hacs == {"name": "Thessla Green", "content_in_root": False}
    assert sorted(path.name for path in (ROOT / "custom_components").iterdir()) == ["thessla_green"]
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
    assert manifest["requirements"] == ["pymodbus==3.13.1", "pyserial==3.5"]


def test_home_assistant_adapter_supports_one_direct_modbus_owner() -> None:
    direct = (INTEGRATION / "direct.py").read_text(encoding="utf-8")
    init_source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    transport = INTEGRATION / "_core" / "protocol" / "transport.py"

    assert transport.is_file()
    assert "PymodbusTransport(endpoint)" in direct
    assert "GatewayService(" in direct
    assert "await entry.runtime_data.api.async_close()" in init_source
    assert "CONNECTION_GATEWAY if CONF_URL in entry.data" in init_source


def test_hacs_exposes_built_in_heater_and_bypass_states_from_one_snapshot() -> None:
    binary_sensor = (INTEGRATION / "binary_sensor.py").read_text(encoding="utf-8")

    assert "ThesslaGreenBypassSensor" in binary_sensor
    assert "ThesslaGreenFpxSensor" in binary_sensor
    assert "ThesslaGreenErvPostHeaterSensor" in binary_sensor
    assert "fpx_stage" in binary_sensor
    assert "erv_post_heater_mode" in binary_sensor


def test_hacs_exposes_native_entities_for_automation_controls() -> None:
    init_source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    fan = (INTEGRATION / "fan.py").read_text(encoding="utf-8")
    select = (INTEGRATION / "select.py").read_text(encoding="utf-8")
    number = (INTEGRATION / "number.py").read_text(encoding="utf-8")

    assert "Platform.NUMBER" in init_source
    assert "FanEntityFeature.SET_SPEED" in fan
    assert "ThesslaGreenModeSelect" in select
    assert "ThesslaGreenSpecialModeSelect" in select
    assert '"manual_fan_speed"' in number
    assert '"temporary_fan_speed"' in number
    assert '"set_fan_speed"' in number
    assert '"set_temporary_fan_speed"' in number
    assert 'command = "activate_temporary_mode"' in number
    assert "async_send_command" in number


def test_hacs_registers_one_ui_for_direct_and_gateway_modes() -> None:
    panel = INTEGRATION / "www" / "panel.js"
    init_source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")

    assert panel.is_file()
    panel_source = panel.read_text(encoding="utf-8")
    assert 'const TAG_NAME = "thessla-green-panel"' in panel_source
    assert "customElements.define(TAG_NAME" in panel_source
    assert "gateway_url" in panel_source
    assert "connection_type" in panel_source
    assert "this._hass.callApi" in panel_source
    assert "properties?.hass" in panel_source
    assert (INTEGRATION / "www" / "direct" / "index.html").is_file()
    assert (INTEGRATION / "www" / "direct" / "app.js").is_file()
    assert (INTEGRATION / "www" / "card.js").is_file()
    assert "async_register_static_paths" in init_source
    assert "async_register_built_in_panel" in init_source
    assert "add_extra_js_url" in init_source
    assert "pymodbus" not in panel_source


def test_hacs_config_flow_defaults_to_read_only_direct_discovery() -> None:
    config_flow = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))

    assert "async_step_direct" in config_flow
    assert "enumerate_serial_ports" in config_flow
    assert "AirPackProbe().run" in config_flow
    assert "PymodbusTransport" in config_flow
    assert "async_step_gateway" in config_flow
    assert "async_step_confirm" in config_flow
    assert "serial_ports" in strings["config"]["step"]["direct"]["description"]
    assert "Bezpośredni Modbus" in strings["config"]["step"]["user"]["menu_options"]["direct"]
    assert "port_busy" in strings["config"]["error"]
    assert "device_not_found" in strings["config"]["error"]


def test_direct_panel_uses_authenticated_home_assistant_bridge() -> None:
    app = (INTEGRATION / "www" / "direct" / "app.js").read_text(encoding="utf-8")
    http = (INTEGRATION / "http.py").read_text(encoding="utf-8")

    assert "thessla-green-request" in app
    assert "window.parent.postMessage" in app
    assert "requires_auth = True" in http
    assert "runtime.coordinator.async_send_command" in http


def test_lovelace_card_auto_discovers_entry_and_reuses_authenticated_bridge() -> None:
    card = (INTEGRATION / "www" / "card.js").read_text(encoding="utf-8")
    http = (INTEGRATION / "http.py").read_text(encoding="utf-8")

    assert 'const CARD_TAG = "thessla-green-card"' in card
    assert "window.customCards.push" in card
    assert "getStubConfig()" in card
    assert "getConfigElement()" in card
    assert 'this._hass.callApi("GET", "thessla_green/config")' in card
    assert "thessla-green-request" in card
    assert "requires_auth = True" in http
    assert 'url = "/api/thessla_green/config"' in http
