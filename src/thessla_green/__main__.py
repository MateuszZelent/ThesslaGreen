"""Command-line entry point for diagnostics and bounded discovery."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from thessla_green import __version__
from thessla_green.application.control import (
    USER_SELECTABLE_SPECIAL_MODES,
    AirPackMode,
)
from thessla_green.application.factory import build_gateway, build_gateway_for_endpoint
from thessla_green.application.gateway import GatewayService
from thessla_green.config import Settings
from thessla_green.discovery.candidates import enumerate_serial_ports
from thessla_green.discovery.service import (
    DiscoverySelectionError,
    DiscoveryService,
    select_unique_airpack,
)
from thessla_green.domain.models import DiscoveryResult, ProbeStatus, TransportKind
from thessla_green.storage import SQLiteStore


def _add_discovery_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--serial-port",
        help="probe this exact serial path (for example /dev/serial/by-id/...)",
    )
    parser.add_argument(
        "--host",
        action="append",
        help="probe this Modbus-TCP host (repeat for multiple hosts)",
    )
    parser.add_argument(
        "--cidr",
        action="append",
        help="probe hosts in this bounded CIDR (repeat for multiple networks)",
    )
    parser.add_argument(
        "--tcp-port",
        action="append",
        type=int,
        help="probe this TCP port (repeat for multiple ports)",
    )
    parser.add_argument(
        "--baudrate",
        action="append",
        type=int,
        help="probe serial ports at this baudrate (repeat for multiple rates)",
    )
    parser.add_argument(
        "--unit-id",
        action="append",
        type=int,
        help="probe this Modbus unit id (repeat for multiple IDs)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="thessla-green")
    subparsers = parser.add_subparsers(dest="command", required=True)
    discover = subparsers.add_parser(
        "discover", help="find AirPack devices using read-only Modbus probes"
    )
    discover.add_argument(
        "--json", action="store_true", help="emit one JSON object containing all results"
    )
    _add_discovery_arguments(discover)
    doctor = subparsers.add_parser(
        "doctor", help="produce a read-only transport and AirPack diagnostic report"
    )
    doctor.add_argument("--json", action="store_true", help="emit the report as JSON")
    _add_discovery_arguments(doctor)
    status = subparsers.add_parser(
        "status", help="read the current AirPack state without writing registers"
    )
    status.add_argument("--json", action="store_true", help="emit the state as JSON")
    status.add_argument(
        "--auto-discover",
        action="store_true",
        help="select exactly one confirmed AirPack before reading the state",
    )
    _add_discovery_arguments(status)
    monitor = subparsers.add_parser(
        "monitor",
        help="collect read-only snapshots for a bounded stability test",
    )
    monitor.add_argument(
        "--duration",
        type=float,
        default=86400.0,
        help="test duration in seconds (default: 86400)",
    )
    monitor.add_argument(
        "--interval",
        type=float,
        help="snapshot interval in seconds (defaults to THESSLA_POLL_INTERVAL_SECONDS)",
    )
    monitor.add_argument("--jsonl", action="store_true", help="emit one JSON snapshot per line")
    monitor.add_argument(
        "--auto-discover",
        action="store_true",
        help="select exactly one confirmed AirPack before monitoring",
    )
    _add_discovery_arguments(monitor)
    control = subparsers.add_parser("control", help="send one explicit, read-confirmed command")
    control_subparsers = control.add_subparsers(dest="control_command", required=True)
    fan = control_subparsers.add_parser("fan-speed", help="set manual fan intensity")
    fan.add_argument("percentage", type=int, choices=range(10, 101))
    temporary_fan = control_subparsers.add_parser(
        "temporary-fan-speed", help="set temporary-mode fan intensity"
    )
    temporary_fan.add_argument("percentage", type=int, choices=range(10, 101))
    mode = control_subparsers.add_parser("mode", help="set automatic/manual/temporary mode")
    mode.add_argument("mode", choices=[item.name.lower() for item in AirPackMode])
    special = control_subparsers.add_parser("special-mode", help="set a documented special mode")
    special.add_argument("mode", choices=list(USER_SELECTABLE_SPECIAL_MODES.values()))
    power = control_subparsers.add_parser("power", help="turn the unit on or off")
    power.add_argument("enabled", choices=("on", "off"))
    control.add_argument("--json", action="store_true", help="emit the confirmed result as JSON")
    control.add_argument(
        "--auto-discover",
        action="store_true",
        help="select exactly one confirmed AirPack before sending the command",
    )
    _add_discovery_arguments(control)
    serve = subparsers.add_parser("serve", help="run the FastAPI gateway as the Modbus owner")
    serve.add_argument("--host", help="HTTP bind address (defaults to THESSLA_API_BIND)")
    serve.add_argument("--port", type=int, help="HTTP port (defaults to THESSLA_API_PORT)")
    serve.add_argument(
        "--demo",
        action="store_true",
        help="run a simulated AirPack4 for local UI/API testing without hardware",
    )
    serve.add_argument(
        "--auto-discover",
        action="store_true",
        help="select exactly one confirmed AirPack from bounded read-only discovery",
    )
    serve.add_argument(
        "--serial-port",
        dest="modbus_serial_port",
        help="Modbus RTU path override; separate from the HTTP --host option",
    )
    serve.add_argument(
        "--modbus-host",
        help="Modbus-TCP host override; separate from the HTTP --host option",
    )
    serve.add_argument("--modbus-port", type=int, help="Modbus-TCP port override")
    serve.add_argument("--unit-id", dest="modbus_unit_id", type=int, help="Modbus unit ID override")
    serve.add_argument("--baudrate", dest="modbus_baudrate", type=int, help="RTU baudrate override")
    backup = subparsers.add_parser(
        "backup", help="create a consistent local SQLite history backup"
    )
    backup.add_argument("--output", required=True, help="destination SQLite file")
    backup.add_argument(
        "--force",
        action="store_true",
        help="replace an existing destination file",
    )
    backup.add_argument("--json", action="store_true", help="emit backup metadata as JSON")
    return parser


def _discovery_settings(
    settings: Settings,
    serial_port: str | None = None,
    *,
    hosts: Sequence[str] | None = None,
    cidrs: Sequence[str] | None = None,
    tcp_ports: Sequence[int] | None = None,
    baudrates: Sequence[int] | None = None,
    unit_ids: Sequence[int] | None = None,
) -> Settings:
    if serial_port:
        settings = replace(
            settings,
            transport=TransportKind.SERIAL,
            serial_port=serial_port,
        )
    if hosts is not None:
        host_values = tuple(hosts)
        settings = replace(
            settings,
            transport=TransportKind.TCP,
            host=host_values[0] if len(host_values) == 1 else None,
            discovery_hosts=host_values,
        )
    if cidrs is not None:
        settings = replace(
            settings,
            transport=TransportKind.TCP,
            host=None,
            discovery_cidrs=tuple(cidrs),
        )
    if tcp_ports is not None:
        port_values = tuple(tcp_ports)
        settings = replace(
            settings,
            transport=TransportKind.TCP,
            modbus_port=port_values[0] if len(port_values) == 1 else settings.modbus_port,
            discovery_ports=port_values,
        )
    if baudrates is not None:
        baud_values = tuple(baudrates)
        settings = replace(
            settings,
            baudrate=baud_values[0] if len(baud_values) == 1 else settings.baudrate,
            discovery_bauds=baud_values,
        )
    if unit_ids is not None:
        unit_values = tuple(unit_ids)
        settings = replace(
            settings,
            device_id=unit_values[0] if len(unit_values) == 1 else settings.device_id,
            discovery_device_ids=unit_values,
        )
    return settings


async def _discover(
    serial_port: str | None = None,
    *,
    hosts: Sequence[str] | None = None,
    cidrs: Sequence[str] | None = None,
    tcp_ports: Sequence[int] | None = None,
    baudrates: Sequence[int] | None = None,
    unit_ids: Sequence[int] | None = None,
) -> tuple[dict[str, Any], ...]:
    settings = _discovery_settings(
        Settings.from_env(),
        serial_port,
        hosts=hosts,
        cidrs=cidrs,
        tcp_ports=tcp_ports,
        baudrates=baudrates,
        unit_ids=unit_ids,
    )
    results = await DiscoveryService(settings).discover(unit_ids=unit_ids)
    return tuple(result.to_dict() for result in results)


def _doctor_report(
    settings: Settings,
    serial_ports: Sequence[dict[str, object]],
    results: Sequence[DiscoveryResult],
) -> dict[str, object]:
    status_counts = {
        status.value: sum(result.status is status for result in results)
        for status in ProbeStatus
    }
    selectable = tuple(result for result in results if result.is_selectable)
    recommendations: list[str] = []

    if not results:
        recommendations.append(
            "Brak kandydatów: podłącz adapter, ustaw stabilny alias /dev/serial/by-id/... "
            "albo podaj jawny --host/--cidr."
        )
    if status_counts[ProbeStatus.PERMISSION_DENIED.value] > 0:
        recommendations.append(
            "Dodaj użytkownika procesu do grupy dialout/uucp i rozpocznij nową sesję logowania."
        )
    if status_counts[ProbeStatus.PORT_BUSY.value] > 0:
        recommendations.append(
            "Zatrzymaj drugi gateway, bezpośrednią integrację Home Assistant lub ModemManager."
        )
    if status_counts[ProbeStatus.DEVICE_NOT_FOUND.value] > 0:
        recommendations.append(
            "Ścieżka urządzenia nie istnieje; sprawdź kabel, udev i alias /dev/serial/by-id/."
        )
    if status_counts[ProbeStatus.NO_RESPONSE.value] > 0:
        recommendations.append(
            "Brak odpowiedzi Modbus: sprawdź 9600 8/N/1, unit-id 10, okablowanie RS-485 "
            "i jednego właściciela magistrali."
        )
    if status_counts[ProbeStatus.UNKNOWN_MODBUS_DEVICE.value] > 0:
        recommendations.append(
            "Odpowiedź Modbus jest poprawna, ale fingerprint nie potwierdza AirPack4; "
            "nie włączaj sterowania bez ręcznej weryfikacji."
        )
    for result in selectable:
        if result.endpoint.kind.value == "serial":
            recommendations.append(
                f"Potwierdzony endpoint: THESSLA_SERIAL_PORT={result.endpoint.address} "
                f"(unit {result.unit_id})."
            )
        else:
            recommendations.append(
                f"Potwierdzony endpoint: THESSLA_HOST={result.endpoint.address} "
                f"THESSLA_MODBUS_PORT={result.endpoint.port} (unit {result.unit_id})."
            )
    if len(selectable) > 1:
        recommendations.append(
            "Wykryto wiele potwierdzonych urządzeń; auto-discover zatrzyma się do czasu "
            "jawnego wyboru endpointu."
        )

    configuration = {
        "transport": settings.transport.value,
        "serial_port": settings.serial_port,
        "host": settings.host,
        "modbus_port": settings.modbus_port,
        "device_id": settings.device_id,
        "baudrate": settings.baudrate,
        "discovery_device_ids": list(settings.discovery_device_ids),
        "discovery_bauds": list(settings.discovery_bauds),
        "discovery_hosts": list(settings.discovery_hosts),
        "discovery_cidrs": list(settings.discovery_cidrs),
        "discovery_ports": list(settings.discovery_ports),
    }
    return {
        "version": __version__,
        "read_only": True,
        "configuration": configuration,
        "serial_ports": list(serial_ports),
        "results": [result.to_dict() for result in results],
        "summary": {
            "candidate_results": len(results),
            "confirmed_airpack": len(selectable),
            "modbus_verified": sum(result.modbus_verified for result in results),
            "status_counts": status_counts,
        },
        "recommendations": list(dict.fromkeys(recommendations)),
    }


async def _doctor(args: argparse.Namespace) -> dict[str, object]:
    settings = _discovery_settings(
        Settings.from_env(),
        args.serial_port,
        hosts=args.host,
        cidrs=args.cidr,
        tcp_ports=args.tcp_port,
        baudrates=args.baudrate,
        unit_ids=args.unit_id,
    )
    serial_ports = tuple(port.to_dict() for port in enumerate_serial_ports())
    results = await DiscoveryService(settings).discover(unit_ids=args.unit_id)
    return _doctor_report(settings, serial_ports, results)


def _print_doctor(report: dict[str, object]) -> None:
    summary = report.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    print(
        f"read_only={report.get('read_only')} version={report.get('version')} "
        f"candidates={summary.get('candidate_results', 0)} "
        f"confirmed_airpack={summary.get('confirmed_airpack', 0)} "
        f"modbus_verified={summary.get('modbus_verified', 0)}"
    )
    results = report.get("results")
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, dict):
                continue
            endpoint = result.get("endpoint")
            endpoint_key = endpoint.get("key", "?") if isinstance(endpoint, dict) else "?"
            print(
                f"{result.get('status')}: {endpoint_key} "
                f"unit={result.get('unit_id')} selectable={result.get('is_selectable')}"
            )
    recommendations = report.get("recommendations")
    if isinstance(recommendations, list):
        for recommendation in recommendations:
            print(f"recommendation: {recommendation}")


def _settings_from_args(args: argparse.Namespace) -> Settings:
    """Apply one-shot endpoint/discovery overrides shared by runtime commands."""

    return _discovery_settings(
        Settings.from_env(),
        getattr(args, "serial_port", None),
        hosts=getattr(args, "host", None),
        cidrs=getattr(args, "cidr", None),
        tcp_ports=getattr(args, "tcp_port", None),
        baudrates=getattr(args, "baudrate", None),
        unit_ids=getattr(args, "unit_id", None),
    )


def _serve_settings(args: argparse.Namespace) -> Settings:
    """Apply explicit Modbus overrides without confusing HTTP bind options."""

    settings = Settings.from_env()
    serial_port = getattr(args, "modbus_serial_port", None)
    modbus_host = getattr(args, "modbus_host", None)
    modbus_port = getattr(args, "modbus_port", None)
    unit_id = getattr(args, "modbus_unit_id", None)
    baudrate = getattr(args, "modbus_baudrate", None)
    if serial_port:
        settings = replace(
            settings,
            transport=TransportKind.SERIAL,
            serial_port=serial_port,
        )
    if modbus_host:
        settings = replace(
            settings,
            transport=TransportKind.TCP,
            host=modbus_host,
            discovery_hosts=(modbus_host,),
        )
    if modbus_port is not None:
        settings = replace(
            settings,
            modbus_port=modbus_port,
            discovery_ports=(modbus_port,),
        )
    if unit_id is not None:
        settings = replace(
            settings,
            device_id=unit_id,
            discovery_device_ids=(unit_id,),
        )
    if baudrate is not None:
        settings = replace(
            settings,
            baudrate=baudrate,
            discovery_bauds=(baudrate,),
        )
    return settings


async def _control(args: argparse.Namespace) -> dict[str, Any]:
    settings = _settings_from_args(args)
    service = (
        await _build_auto_discovered_gateway(settings)
        if args.auto_discover
        else build_gateway(settings)
    )
    if service is None:
        raise RuntimeError(
            "configure THESSLA_SERIAL_PORT or THESSLA_HOST before sending a control command"
        )
    await service.start()
    try:
        if args.control_command == "fan-speed":
            result = await service.set_fan_speed(args.percentage, source="cli")
        elif args.control_command == "temporary-fan-speed":
            result = await service.set_temporary_fan_speed(args.percentage, source="cli")
        elif args.control_command == "mode":
            selected_mode = AirPackMode[args.mode.upper()]
            if selected_mode is AirPackMode.TEMPORARY:
                percentage = service.state.values.get("temporary_fan_speed")
                if not isinstance(percentage, int) or isinstance(percentage, bool):
                    raise RuntimeError("current temporary fan speed is unavailable")
                result = await service.activate_temporary_mode(percentage, source="cli")
            else:
                result = await service.set_mode(selected_mode, source="cli")
        elif args.control_command == "special-mode":
            names = {name: mode for mode, name in USER_SELECTABLE_SPECIAL_MODES.items()}
            result = await service.set_special_mode(names[args.mode], source="cli")
        else:
            result = await service.set_power(args.enabled == "on", source="cli")
        return {"status": "confirmed", "result": result.to_dict(), "state": service.state.to_dict()}
    finally:
        await service.stop()


async def _backup(args: argparse.Namespace) -> dict[str, object]:
    settings = Settings.from_env()
    store = SQLiteStore(
        settings.database_url,
        max_state_rows=settings.telemetry_retention_rows,
        max_audit_rows=settings.audit_retention_rows,
        max_command_rows=settings.command_cache_retention_rows,
    )
    await store.initialize()
    await store.backup_to(args.output, overwrite=args.force)
    return {
        "source": settings.database_url,
        "destination": str(args.output),
        "overwrote_existing": bool(args.force),
        "read_only_modbus": True,
    }


async def _status(
    *, auto_discover: bool = False, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or Settings.from_env()
    service = (
        await _build_auto_discovered_gateway(settings)
        if auto_discover
        else build_gateway(settings)
    )
    if service is None:
        raise RuntimeError(
            "configure THESSLA_SERIAL_PORT or THESSLA_HOST before reading the device state"
        )
    await service.start()
    try:
        return service.state.to_dict()
    finally:
        await service.stop()


async def _monitor(
    duration: float,
    interval: float | None,
    jsonl: bool,
    *,
    auto_discover: bool = False,
    settings: Settings | None = None,
) -> None:
    if duration <= 0:
        raise ValueError("monitor duration must be positive")
    settings = settings or Settings.from_env()
    service = (
        await _build_auto_discovered_gateway(settings)
        if auto_discover
        else build_gateway(settings)
    )
    if service is None:
        raise RuntimeError(
            "configure THESSLA_SERIAL_PORT or THESSLA_HOST before monitoring the device"
        )
    selected_interval = interval if interval is not None else settings.poll_interval_seconds
    if selected_interval <= 0:
        raise ValueError("monitor interval must be positive")
    await service.start()
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + duration
        while True:
            snapshot = service.state.to_dict()
            if jsonl:
                print(
                    json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                    flush=True,
                )
            else:
                values = snapshot.get("values", {})
                values = values if isinstance(values, dict) else {}
                print(
                    f"captured_at={snapshot.get('captured_at')} online={snapshot.get('online')} "
                    f"revision={snapshot.get('revision')} "
                    f"manual={values.get('manual_fan_speed')}% "
                    f"temporary={values.get('temporary_fan_speed')}% "
                    f"supply={values.get('supply_airflow')} "
                    f"extract={values.get('extract_airflow')}",
                    flush=True,
                )
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(selected_interval, remaining))
            if loop.time() < deadline:
                await service.refresh()
    finally:
        await service.stop()


async def _build_auto_discovered_gateway(settings: Settings) -> GatewayService:
    results = await DiscoveryService(settings).discover()
    try:
        selected = select_unique_airpack(results)
    except DiscoverySelectionError as exc:
        report = json.dumps(
            [result.to_dict() for result in results],
            ensure_ascii=False,
            indent=2,
        )
        raise RuntimeError(f"{exc}\nDiscovery results:\n{report}") from exc
    return build_gateway_for_endpoint(
        settings,
        selected.endpoint,
        unit_id=selected.unit_id,
    )


def _serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - deployment dependency
        raise RuntimeError("install the API dependencies before running the gateway") from exc

    settings = _serve_settings(args)
    from thessla_green.api.app import create_app

    if args.demo and args.auto_discover:
        raise RuntimeError("--demo and --auto-discover cannot be used together")
    if args.auto_discover:
        discovered_service = asyncio.run(_build_auto_discovered_gateway(settings))
        uvicorn.run(
            create_app(
                discovered_service,
                api_token=settings.api_token,
                cors_origins=settings.api_cors_origins,
                poll_interval_seconds=settings.poll_interval_seconds,
            ),
            host=args.host or settings.api_bind,
            port=args.port or settings.api_port,
            log_level="info",
        )
        return 0
    if args.demo:
        from thessla_green.application.gateway import GatewayService
        from thessla_green.protocol.simulator import SimulatedAirPackTransport

        transport = SimulatedAirPackTransport(unit_id=settings.device_id)
        demo_service = GatewayService(
            transport,
            endpoint=transport.endpoint,
            unit_id=transport.unit_id,
            airflow_observation_seconds=settings.airflow_observation_seconds,
            airflow_observation_interval_seconds=settings.airflow_observation_interval_seconds,
        )
        uvicorn.run(
            create_app(
                demo_service,
                api_token=settings.api_token,
                cors_origins=settings.api_cors_origins,
                poll_interval_seconds=settings.poll_interval_seconds,
            ),
            host=args.host or settings.api_bind,
            port=args.port or settings.api_port,
            log_level="info",
        )
        return 0
    configured_service = build_gateway(settings)
    uvicorn.run(
        create_app(
            configured_service,
            api_token=settings.api_token,
            cors_origins=settings.api_cors_origins,
            poll_interval_seconds=settings.poll_interval_seconds,
        ),
        host=args.host or settings.api_bind,
        port=args.port or settings.api_port,
        log_level="info",
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "discover":
        results = asyncio.run(
            _discover(
                args.serial_port,
                hosts=args.host,
                cidrs=args.cidr,
                tcp_ports=args.tcp_port,
                baudrates=args.baudrate,
                unit_ids=args.unit_id,
            )
        )
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            for result in results:
                identity = result.get("identity") or {}
                print(
                    f"{result['status']}: {result['endpoint']['key']} "
                    f"unit={result['unit_id']} model={identity.get('model', '-')} "
                    f"serial={identity.get('serial_number', '-')}"
                )
        return 0
    if args.command == "doctor":
        report = asyncio.run(_doctor(args))
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            _print_doctor(report)
        return 0
    if args.command == "status":
        state = asyncio.run(
            _status(auto_discover=args.auto_discover, settings=_settings_from_args(args))
        )
        if args.json:
            print(json.dumps(state, ensure_ascii=False, indent=2))
        else:
            values = state.get("values", {})
            values = values if isinstance(values, dict) else {}
            print(
                f"online={state.get('online')} mode={values.get('mode')} "
                f"manual={values.get('manual_fan_speed')}% "
                f"temporary={values.get('temporary_fan_speed')}% "
                f"supply={values.get('supply_airflow')} m3/h "
                f"extract={values.get('extract_airflow')} m3/h"
            )
        return 0
    if args.command == "monitor":
        asyncio.run(
            _monitor(
                args.duration,
                args.interval,
                args.jsonl,
                auto_discover=args.auto_discover,
                settings=_settings_from_args(args),
            )
        )
        return 0
    if args.command == "control":
        control_result: dict[str, Any] = asyncio.run(_control(args))
        if args.json:
            print(json.dumps(control_result, ensure_ascii=False, indent=2))
        else:
            print(
                f"confirmed: {control_result['result']['command']} "
                f"{control_result['result']['register']}={control_result['result']['confirmed_value']}"
            )
        return 0
    if args.command == "backup":
        result = asyncio.run(_backup(args))
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"backup: {result['destination']}")
        return 0
    if args.command == "serve":
        return _serve(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
