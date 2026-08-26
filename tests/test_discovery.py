from __future__ import annotations

import asyncio
import errno
import os
from collections.abc import Sequence
from pathlib import Path

import pytest

from thessla_green.config import Settings
from thessla_green.discovery.candidates import _stable_serial_aliases
from thessla_green.discovery.service import (
    DiscoveryService,
    discovery_endpoints,
    select_unique_airpack,
)
from thessla_green.domain.models import (
    DiscoveryResult,
    ProbeStatus,
    TransportEndpoint,
    TransportKind,
)
from thessla_green.protocol.transport import ReadResponseError


class FakeAirPackTransport:
    def __init__(self, endpoint: TransportEndpoint) -> None:
        self.endpoint = endpoint
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.connected = False

    async def read_input_registers(self, address: int, count: int, unit_id: int) -> tuple[int, ...]:
        if address == 0 and count == 5:
            return (4, 84, 0, 0, 2)
        if address == 16 and count == 7:
            return (215, 220, 225, 230, 235, 240, 245)
        if address == 24 and count == 6:
            return (0x001A, 0x002B, 0x003C, 0x004D, 0x005E, 0x006F)
        raise AssertionError((address, count, unit_id))

    async def read_holding_registers(
        self, address: int, count: int, unit_id: int
    ) -> tuple[int, ...]:
        raise AssertionError("discovery must not read holding registers")

    async def read_coils(self, address: int, count: int, unit_id: int) -> tuple[bool, ...]:
        raise AssertionError("discovery must not read coils")

    async def read_discrete_inputs(
        self, address: int, count: int, unit_id: int
    ) -> tuple[bool, ...]:
        raise AssertionError("discovery must not read discrete inputs")

    async def write_holding_register(self, address: int, value: int, unit_id: int) -> None:
        raise AssertionError("discovery must never write")

    async def write_holding_registers(
        self, address: int, values: Sequence[int], unit_id: int
    ) -> None:
        raise AssertionError("discovery must never write")


class PermissionDeniedTransport(FakeAirPackTransport):
    async def connect(self) -> None:
        raise PermissionError("permission denied opening /dev/serial/by-id/adapter")


class BusyPortTransport(FakeAirPackTransport):
    async def connect(self) -> None:
        from thessla_green.protocol.transport import SerialPortBusy

        raise SerialPortBusy("serial port is busy: /dev/serial/by-id/adapter")


class BusyOSErrorTransport(FakeAirPackTransport):
    async def connect(self) -> None:
        raise OSError(errno.EAGAIN, "Could not exclusively lock port /dev/ttyUSB0")


class UnknownModbusTransport(FakeAirPackTransport):
    async def read_input_registers(
        self, address: int, count: int, unit_id: int
    ) -> tuple[int, ...]:
        if address == 0 and count == 5:
            return (2, 1, 0, 0, 1)
        return await super().read_input_registers(address, count, unit_id)


class TimeoutTransport(FakeAirPackTransport):
    async def read_input_registers(
        self, address: int, count: int, unit_id: int
    ) -> tuple[int, ...]:
        raise TimeoutError("probe timeout")


class MalformedTransport(FakeAirPackTransport):
    async def read_input_registers(
        self, address: int, count: int, unit_id: int
    ) -> tuple[int, ...]:
        if address == 0 and count == 5:
            return (4, 84)
        return await super().read_input_registers(address, count, unit_id)


class InvalidTemperatureFingerprintTransport(FakeAirPackTransport):
    async def read_input_registers(
        self, address: int, count: int, unit_id: int
    ) -> tuple[int, ...]:
        if address == 16 and count == 7:
            return (1000, 220, 225, 230, 235, 240, 245)
        return await super().read_input_registers(address, count, unit_id)


class ExperimentalFirmwareTransport(FakeAirPackTransport):
    async def read_input_registers(
        self, address: int, count: int, unit_id: int
    ) -> tuple[int, ...]:
        if address == 0 and count == 5:
            return (95, 12, 0, 0, 34)
        return await super().read_input_registers(address, count, unit_id)


class ExceptionResponseTransport(FakeAirPackTransport):
    async def read_input_registers(
        self, address: int, count: int, unit_id: int
    ) -> tuple[int, ...]:
        raise ReadResponseError("Modbus exception response")


def test_discovery_endpoints_are_bounded_and_deduplicated() -> None:
    settings = Settings(
        discovery_hosts=("192.0.2.10",),
        discovery_cidrs=("192.0.2.0/30",),
        discovery_ports=(502,),
    )

    endpoints = discovery_endpoints(settings, serial_ports=())
    assert [endpoint.key for endpoint in endpoints] == [
        "tcp://192.0.2.10:502",
        "tcp://192.0.2.1:502",
        "tcp://192.0.2.2:502",
    ]


def test_configured_serial_path_is_the_only_serial_candidate() -> None:
    settings = Settings(serial_port="/dev/serial/by-id/adapter")

    endpoints = discovery_endpoints(
        settings,
        # Automatic enumeration must not override an explicit stable path.
        serial_ports=(),
    )

    assert [endpoint.key for endpoint in endpoints] == ["serial:///dev/serial/by-id/adapter"]


def test_stable_serial_aliases_resolve_to_by_id_paths(tmp_path: Path) -> None:
    target = tmp_path / "ttyUSB0"
    target.touch()
    alias_directory = tmp_path / "by-id"
    alias_directory.mkdir()
    alias = alias_directory / "usb-FTDI_FT232R_USB_UART_BG03ZCK6-if00-port0"
    alias.symlink_to(os.path.relpath(target, alias_directory))

    assert _stable_serial_aliases(alias_directory) == {
        str(target): str(alias),
    }


def test_discovery_identifies_airpack_from_read_only_fingerprint() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.TCP, "192.0.2.10", port=502)
        settings = Settings(discovery_device_ids=(10,))
        service = DiscoveryService(settings, transport_factory=FakeAirPackTransport)

        results = await service.discover(endpoints=(endpoint,))

        assert len(results) == 1
        result = results[0]
        assert result.status is ProbeStatus.AIRPACK
        assert result.identity is not None
        assert result.identity.firmware == (4, 84, 2)
        assert result.identity.serial_number == "1a2b 3c4d 5e6f"
        assert result.evidence["read_only"] is True
        assert result.modbus_verified

    asyncio.run(run())


def test_discovery_rejects_values_outside_the_pdf_fingerprint() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.TCP, "192.0.2.30", port=502)
        result = (
            await DiscoveryService(
                Settings(discovery_device_ids=(10,)),
                transport_factory=InvalidTemperatureFingerprintTransport,
            ).discover(endpoints=(endpoint,))
        )[0]

        assert result.status is ProbeStatus.UNKNOWN_MODBUS_DEVICE
        assert not result.is_selectable
        assert "-999..999" in (result.error or "")

    asyncio.run(run())


def test_discovery_accepts_documented_9x_test_firmware() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.TCP, "192.0.2.31", port=502)
        result = (
            await DiscoveryService(
                Settings(discovery_device_ids=(10,)),
                transport_factory=ExperimentalFirmwareTransport,
            ).discover(endpoints=(endpoint,))
        )[0]

        assert result.status is ProbeStatus.AIRPACK
        assert result.identity is not None
        assert result.identity.firmware == (95, 12, 34)

    asyncio.run(run())


def test_discovery_reports_serial_permission_errors_separately() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(
            TransportKind.SERIAL,
            "/dev/serial/by-id/adapter",
        )
        service = DiscoveryService(
            Settings(discovery_device_ids=(10,)),
            transport_factory=PermissionDeniedTransport,
        )

        results = await service.discover(endpoints=(endpoint,))

        assert len(results) == 1
        assert results[0].status is ProbeStatus.PERMISSION_DENIED
        assert "dialout/uucp" in (results[0].error or "")

    asyncio.run(run())


def test_discovery_reports_a_busy_serial_port_separately() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/serial/by-id/adapter")
        service = DiscoveryService(
            Settings(discovery_device_ids=(10,)),
            transport_factory=BusyPortTransport,
        )

        results = await service.discover(endpoints=(endpoint,))

        assert len(results) == 1
        assert results[0].status is ProbeStatus.PORT_BUSY
        assert "busy" in (results[0].error or "")

    asyncio.run(run())


def test_discovery_classifies_pyserial_exclusive_lock_os_error() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyUSB0")
        service = DiscoveryService(
            Settings(discovery_device_ids=(10,)),
            transport_factory=BusyOSErrorTransport,
        )

        results = await service.discover(endpoints=(endpoint,))

        assert len(results) == 1
        assert results[0].status is ProbeStatus.PORT_BUSY

    asyncio.run(run())


def test_discovery_keeps_unknown_modbus_response_non_selectable() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.TCP, "192.0.2.20", port=502)
        service = DiscoveryService(
            Settings(discovery_device_ids=(10,)),
            transport_factory=UnknownModbusTransport,
        )

        result = (await service.discover(endpoints=(endpoint,)))[0]

        assert result.status is ProbeStatus.UNKNOWN_MODBUS_DEVICE
        assert result.to_dict()["status"] == "unknown_modbus_device"
        assert result.modbus_verified
        assert not result.is_selectable

    asyncio.run(run())


def test_discovery_reports_timeout_and_exception_responses_as_no_response() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.TCP, "192.0.2.21", port=502)
        for factory in (TimeoutTransport, ExceptionResponseTransport):
            service = DiscoveryService(
                Settings(discovery_device_ids=(10,)),
                transport_factory=factory,
            )
            result = (await service.discover(endpoints=(endpoint,)))[0]
            assert result.status is ProbeStatus.NO_RESPONSE

    asyncio.run(run())


def test_discovery_reports_malformed_fingerprint_as_unknown_modbus_device() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.TCP, "192.0.2.22", port=502)
        service = DiscoveryService(
            Settings(discovery_device_ids=(10,)),
            transport_factory=MalformedTransport,
        )

        result = (await service.discover(endpoints=(endpoint,)))[0]

        assert result.status is ProbeStatus.UNKNOWN_MODBUS_DEVICE
        assert not result.is_selectable

    asyncio.run(run())


def test_discovery_is_repeatable_and_exposes_duplicate_paths_without_claiming_one() -> None:
    async def run() -> None:
        endpoints = (
            TransportEndpoint(TransportKind.TCP, "192.0.2.30", port=502),
            TransportEndpoint(TransportKind.TCP, "192.0.2.31", port=502),
        )
        service = DiscoveryService(
            Settings(discovery_device_ids=(10,)),
            transport_factory=FakeAirPackTransport,
        )

        first = await service.discover(endpoints=endpoints)
        second = await service.discover(endpoints=endpoints)

        assert [result.identity.stable_id for result in first if result.identity] == [
            result.identity.stable_id for result in second if result.identity
        ]
        assert len({result.identity.stable_id for result in first if result.identity}) == 1
        assert all(result.is_selectable for result in first)

    asyncio.run(run())


def test_auto_selection_accepts_exactly_one_confirmed_airpack() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.TCP, "192.0.2.40", port=502)
        service = DiscoveryService(
            Settings(discovery_device_ids=(10,)),
            transport_factory=FakeAirPackTransport,
        )
        results = await service.discover(endpoints=(endpoint,))

        selected = select_unique_airpack(results)
        assert selected.is_selectable
        assert selected.endpoint == endpoint

    asyncio.run(run())


def test_auto_selection_fails_closed_for_zero_or_multiple_devices() -> None:
    no_device = DiscoveryResult(
        endpoint=TransportEndpoint(TransportKind.TCP, "192.0.2.41", port=502),
        unit_id=10,
        status=ProbeStatus.NO_RESPONSE,
    )
    with pytest.raises(RuntimeError, match="no confirmed"):
        select_unique_airpack((no_device,))

    async def run_multiple() -> None:
        endpoints = (
            TransportEndpoint(TransportKind.TCP, "192.0.2.42", port=502),
            TransportEndpoint(TransportKind.TCP, "192.0.2.43", port=502),
        )
        service = DiscoveryService(
            Settings(discovery_device_ids=(10,)),
            transport_factory=FakeAirPackTransport,
        )
        results = await service.discover(endpoints=endpoints)
        with pytest.raises(RuntimeError, match="multiple"):
            select_unique_airpack(results)

    asyncio.run(run_multiple())
