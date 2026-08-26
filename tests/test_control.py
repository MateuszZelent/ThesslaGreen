from __future__ import annotations

import asyncio

import pytest

from thessla_green.application.control import (
    AirPackController,
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
        value = self.registers.get(address, 0)
        if self.mismatch and address in self.registers:
            value += 1
        return (value,) + tuple(0 for _ in range(count - 1))

    async def read_coils(self, address: int, count: int, unit_id: int) -> tuple[bool, ...]:
        return tuple(False for _ in range(count))

    async def read_discrete_inputs(
        self, address: int, count: int, unit_id: int
    ) -> tuple[bool, ...]:
        return tuple(False for _ in range(count))

    async def write_holding_register(self, address: int, value: int, unit_id: int) -> None:
        self.writes.append((address, value, unit_id))
        self.registers[address] = value


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

        assert transport.writes == []

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
