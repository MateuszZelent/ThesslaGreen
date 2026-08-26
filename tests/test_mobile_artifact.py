from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
MOBILE = ROOT / "mobile"


def test_flutter_screen_uses_the_typed_gateway_client() -> None:
    pubspec = (MOBILE / "pubspec.yaml").read_text(encoding="utf-8")
    source = (MOBILE / "lib" / "main.dart").read_text(encoding="utf-8")

    assert "flutter:" in pubspec
    assert "sdk: flutter" in pubspec
    assert "runApp" in source
    assert "ThesslaGatewayClient" in source
    assert "sendCommand" in source
    assert "activate_temporary_mode" in source
    assert "Automatyczny" in source
    assert "Chwilowy" in source
    assert "potwierdzone read-back" in source
    assert "_state = response.state" in source

    client = (MOBILE / "lib" / "thessla_gateway_client.dart").read_text(encoding="utf-8")
    assert "X-Thessla-Source" in client


def test_mobile_screen_does_not_import_modbus_or_write_registers() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in (MOBILE / "lib").glob("*.dart"))

    assert "pymodbus" not in source.lower()
    assert "write_register" not in source
    assert "write_holding_register" not in source
