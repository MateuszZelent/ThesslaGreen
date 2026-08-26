from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from thessla_green.__main__ import (
    _doctor_report,
    _serve_settings,
    _settings_from_args,
    _status,
    build_parser,
    main,
)
from thessla_green.application.gateway import GatewayService
from thessla_green.config import Settings
from thessla_green.domain.models import (
    DeviceIdentity,
    DiscoveryResult,
    ProbeStatus,
    TransportEndpoint,
    TransportKind,
)
from thessla_green.protocol.simulator import SimulatedAirPackTransport


def test_discovery_cli_accepts_bounded_network_and_serial_overrides() -> None:
    args = build_parser().parse_args(
        [
            "discover",
            "--host",
            "192.0.2.10",
            "--cidr",
            "192.0.2.0/30",
            "--tcp-port",
            "502",
            "--baudrate",
            "9600",
            "--unit-id",
            "10",
            "--json",
        ]
    )

    assert args.host == ["192.0.2.10"]
    assert args.cidr == ["192.0.2.0/30"]
    assert args.tcp_port == [502]
    assert args.baudrate == [9600]
    assert args.unit_id == [10]
    assert args.json is True


def test_monitor_cli_defaults_to_one_day_and_supports_jsonl() -> None:
    args = build_parser().parse_args(
        ["monitor", "--interval", "5", "--jsonl", "--auto-discover"]
    )

    assert args.duration == 86400.0
    assert args.interval == 5.0
    assert args.jsonl is True
    assert args.auto_discover is True


def test_status_and_control_cli_expose_auto_discovery() -> None:
    status = build_parser().parse_args(
        [
            "status",
            "--auto-discover",
            "--serial-port",
            "/dev/serial/by-id/adapter",
            "--json",
        ]
    )
    control = build_parser().parse_args(
        [
            "control",
            "--auto-discover",
            "--serial-port",
            "/dev/serial/by-id/adapter",
            "--json",
            "mode",
            "manual",
        ]
    )

    assert status.auto_discover is True
    assert status.json is True
    assert status.serial_port.endswith("/adapter")
    assert control.auto_discover is True
    assert control.json is True
    assert control.serial_port.endswith("/adapter")
    assert control.control_command == "mode"


def test_monitor_cli_accepts_one_shot_endpoint_overrides() -> None:
    args = build_parser().parse_args(
        [
            "monitor",
            "--serial-port",
            "/dev/serial/by-id/adapter",
            "--unit-id",
            "10",
        ]
    )

    assert args.serial_port.endswith("/adapter")
    assert args.unit_id == [10]


def test_one_shot_endpoint_override_selects_matching_transport() -> None:
    serial_args = build_parser().parse_args(
        ["status", "--serial-port", "/dev/serial/by-id/adapter"]
    )
    tcp_args = build_parser().parse_args(
        ["status", "--host", "192.0.2.10", "--tcp-port", "502", "--unit-id", "11"]
    )

    serial_settings = _settings_from_args(serial_args)
    tcp_settings = _settings_from_args(tcp_args)
    assert serial_settings.transport is TransportKind.SERIAL
    assert serial_settings.serial_port == "/dev/serial/by-id/adapter"
    assert tcp_settings.transport is TransportKind.TCP
    assert tcp_settings.host == "192.0.2.10"
    assert tcp_settings.modbus_port == 502
    assert tcp_settings.device_id == 11


def test_doctor_parser_accepts_read_only_discovery_overrides() -> None:
    args = build_parser().parse_args(
        [
            "doctor",
            "--json",
            "--serial-port",
            "/dev/serial/by-id/adapter",
            "--unit-id",
            "10",
        ]
    )

    assert args.json is True
    assert args.serial_port.endswith("/adapter")
    assert args.unit_id == [10]


def test_doctor_report_contains_safe_summary_and_endpoint_hint() -> None:
    endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/serial/by-id/adapter")
    result = DiscoveryResult(
        endpoint=endpoint,
        unit_id=10,
        status=ProbeStatus.AIRPACK,
        identity=DeviceIdentity(
            model="AirPack4",
            unit_id=10,
            firmware=(4, 85, 16),
            serial_number="007e 00df",
            endpoint=endpoint,
        ),
    )

    report = _doctor_report(
        Settings(serial_port=endpoint.address),
        [{"device": endpoint.address}],
        [result],
    )

    assert report["read_only"] is True
    summary = report["summary"]
    assert isinstance(summary, dict)
    assert summary["confirmed_airpack"] == 1
    recommendations = report["recommendations"]
    assert isinstance(recommendations, list)
    assert any("THESSLA_SERIAL_PORT=" in str(item) for item in recommendations)


def test_serve_cli_exposes_fail_closed_auto_discovery_mode() -> None:
    args = build_parser().parse_args(
        [
            "serve",
            "--auto-discover",
            "--port",
            "18089",
            "--serial-port",
            "/dev/serial/by-id/adapter",
            "--unit-id",
            "10",
        ]
    )

    assert args.auto_discover is True
    assert args.demo is False
    assert args.port == 18089
    assert args.modbus_serial_port.endswith("/adapter")
    assert args.modbus_unit_id == 10


def test_serve_modbus_overrides_do_not_reuse_http_host_option() -> None:
    args = build_parser().parse_args(
        [
            "serve",
            "--host",
            "0.0.0.0",
            "--modbus-host",
            "192.0.2.10",
            "--modbus-port",
            "502",
            "--unit-id",
            "11",
        ]
    )

    settings = _serve_settings(args)
    assert settings.transport is TransportKind.TCP
    assert settings.host == "192.0.2.10"
    assert settings.modbus_port == 502
    assert settings.device_id == 11


def test_backup_cli_requires_an_explicit_output_and_force_flag() -> None:
    args = build_parser().parse_args(["backup", "--output", "/tmp/thessla-backup.db", "--json"])

    assert args.output == "/tmp/thessla-backup.db"
    assert args.json is True
    assert args.force is False


def test_status_auto_discover_uses_the_selected_gateway() -> None:
    async def run() -> None:
        transport = SimulatedAirPackTransport()
        gateway = GatewayService(transport, endpoint=transport.endpoint, unit_id=transport.unit_id)

        async def selected(_settings: Settings) -> GatewayService:
            return gateway

        with patch("thessla_green.__main__._build_auto_discovered_gateway", new=selected):
            state = await _status(auto_discover=True)

        assert state["online"] is True
        assert state["identity"] is not None

    asyncio.run(run())


def test_status_reports_missing_one_shot_port_without_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        ["status", "--serial-port", "/tmp/thessla-green-does-not-exist", "--json"]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err.startswith("error: serial device not found:")
    assert "Traceback" not in captured.err
