from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from thessla_green.application.control import (
    AirPackController,
    ComfortPreference,
    ControlVerificationError,
    IdentityNotConfirmed,
    SpecialMode,
    UnsupportedControl,
)
from thessla_green.domain.models import (
    Capabilities,
    DeviceIdentity,
    TransportEndpoint,
    TransportKind,
)


class FakeTransport:
    def __init__(self, *, mismatch: bool = False) -> None:
        self.endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        self.registers: dict[int, int] = {}
        self.writes: list[tuple[int, int, int]] = []
        self.write_blocks: list[tuple[int, tuple[int, ...], int]] = []
        self.mismatch = mismatch

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def read_input_registers(self, address: int, count: int, unit_id: int) -> tuple[int, ...]:
        return tuple(0 for _ in range(count))

    async def read_holding_registers(
        self, address: int, count: int, unit_id: int
    ) -> tuple[int, ...]:
        values = tuple(self.registers.get(address + offset, 0) for offset in range(count))
        if self.mismatch and address in self.registers:
            values = (values[0] + 1, *values[1:])
        return values

    async def read_coils(self, address: int, count: int, unit_id: int) -> tuple[bool, ...]:
        return tuple(False for _ in range(count))

    async def read_discrete_inputs(
        self, address: int, count: int, unit_id: int
    ) -> tuple[bool, ...]:
        return tuple(False for _ in range(count))

    async def write_holding_register(self, address: int, value: int, unit_id: int) -> None:
        self.writes.append((address, value, unit_id))
        self.registers[address] = value

    async def write_holding_registers(
        self, address: int, values: Sequence[int], unit_id: int
    ) -> None:
        normalized = tuple(values)
        self.write_blocks.append((address, normalized, unit_id))
        if address == 4400 and len(normalized) == 3 and normalized[2] == 1:
            self.registers[4208] = normalized[0]
            self.registers[4211] = normalized[1]


def test_manual_fan_speed_is_written_and_confirmed() -> None:
    async def run() -> None:
        transport = FakeTransport()
        controller = AirPackController(
            transport,
            endpoint=transport.endpoint,
            unit_id=10,
            identity=DeviceIdentity(model="AirPack4", unit_id=10),
        )

        result = await controller.set_fan_speed(60, source="mobile")

        assert result.confirmed
        assert result.register == "manual_fan_speed"
        assert result.source == "mobile"
        assert result.audit_sequence == 1
        assert controller.audit_events[0].success
        assert controller.audit_events[0].source == "mobile"
        assert transport.writes == [(4210, 60, 10)]

    asyncio.run(run())


def test_special_mode_helpers_use_documented_values() -> None:
    async def run() -> None:
        transport = FakeTransport()
        controller = AirPackController(
            transport,
            endpoint=transport.endpoint,
            unit_id=10,
            identity=DeviceIdentity(model="AirPack4", unit_id=10),
        )

        await controller.set_fireplace()
        await controller.set_open_windows()
        await controller.set_special_mode(SpecialMode.NONE)

        assert transport.writes == [(4224, 2, 10), (4224, 10, 10), (4224, 0, 10)]

    asyncio.run(run())


def test_eco_and_comfort_modes_use_documented_register() -> None:
    async def run() -> None:
        transport = FakeTransport()
        controller = AirPackController(
            transport,
            endpoint=transport.endpoint,
            unit_id=10,
            identity=DeviceIdentity(model="AirPack4", unit_id=10),
        )

        eco = await controller.set_comfort_mode(ComfortPreference.ECO, source="web")
        comfort = await controller.set_comfort_mode(ComfortPreference.COMFORT, source="web")

        assert eco.confirmed and comfort.confirmed
        assert eco.register == comfort.register == "comfort_mode_panel"
        assert transport.writes == [(4304, 0, 10), (4304, 1, 10)]

    asyncio.run(run())


def test_temporary_fan_speed_is_written_and_confirmed() -> None:
    async def run() -> None:
        transport = FakeTransport()
        controller = AirPackController(
            transport,
            endpoint=transport.endpoint,
            unit_id=10,
            identity=DeviceIdentity(model="AirPack4", unit_id=10),
        )

        result = await controller.set_temporary_fan_speed(70)

        assert result.confirmed
        assert result.register == "temporary_fan_speed"
        assert transport.writes == [(4211, 70, 10)]

    asyncio.run(run())


def test_temporary_mode_is_activated_with_one_documented_register_block() -> None:
    async def run() -> None:
        transport = FakeTransport()
        controller = AirPackController(
            transport,
            endpoint=transport.endpoint,
            unit_id=10,
            identity=DeviceIdentity(model="AirPack4", unit_id=10),
        )

        result = await controller.activate_temporary_mode(70, source="web")

        assert result.confirmed
        assert result.command == "activate_temporary_mode"
        assert result.register == "temporary_activation_speed"
        assert transport.write_blocks == [(4400, (2, 70, 1), 10)]
        assert transport.writes == []

    asyncio.run(run())


def test_invalid_speed_does_not_write() -> None:
    async def run() -> None:
        transport = FakeTransport()
        controller = AirPackController(
            transport,
            endpoint=transport.endpoint,
            unit_id=10,
            identity=DeviceIdentity(model="AirPack4", unit_id=10),
        )

        with pytest.raises(ValueError):
            await controller.set_fan_speed(9)
        with pytest.raises(ValueError):
            await controller.set_fan_speed(101)
        with pytest.raises(ValueError):
            await controller.activate_temporary_mode(9)
        with pytest.raises(ValueError, match="activate_temporary_mode"):
            await controller.set_mode(2)

        assert transport.writes == []
        assert transport.write_blocks == []

    asyncio.run(run())


def test_read_back_mismatch_is_rejected() -> None:
    async def run() -> None:
        transport = FakeTransport(mismatch=True)
        controller = AirPackController(
            transport,
            endpoint=transport.endpoint,
            unit_id=10,
            identity=DeviceIdentity(model="AirPack4", unit_id=10),
        )

        with pytest.raises(ControlVerificationError):
            await controller.set_fan_speed(60)

        assert len(controller.audit_events) == 1
        assert not controller.audit_events[0].success
        assert controller.audit_events[0].confirmed_value == 61

    asyncio.run(run())


def test_control_requires_read_only_identity_confirmation() -> None:
    async def run() -> None:
        transport = FakeTransport()
        controller = AirPackController(transport, endpoint=transport.endpoint, unit_id=10)

        with pytest.raises(IdentityNotConfirmed):
            await controller.set_fan_speed(60)
        assert transport.writes == []

    asyncio.run(run())


def test_control_rejects_capability_not_advertised_by_profile() -> None:
    async def run() -> None:
        transport = FakeTransport()
        controller = AirPackController(
            transport,
            endpoint=transport.endpoint,
            unit_id=10,
            identity=DeviceIdentity(model="AirPack4", unit_id=10),
            capabilities=Capabilities(features=frozenset({"mode"})),
        )

        with pytest.raises(UnsupportedControl, match="capability manual_fan_speed"):
            await controller.set_fan_speed(60)
        assert transport.writes == []

    asyncio.run(run())
