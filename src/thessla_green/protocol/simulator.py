"""Deterministic AirPack4 transport for integration tests and local demos.

The simulator implements the same small :class:`ModbusTransport` boundary as
the PyModbus adapter.  It never opens a device or socket, but it models the
documented identification, control and airflow registers closely enough to
exercise the gateway, API and Home Assistant adapters without hardware.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

from thessla_green.domain.models import TransportEndpoint, TransportKind
from thessla_green.protocol.transport import ModbusTransportError, ReadResponseError


def _encode_temperature(value: float | None) -> int:
    """Encode a Celsius value using the vendor's signed tenths format."""

    if value is None:
        return 0x8000
    raw = round(value * 10)
    if not -32768 <= raw <= 32767:
        raise ValueError("simulated temperature is outside the int16 range")
    return raw if raw >= 0 else raw + 0x10000


class SimulatedAirPackTransport:
    """In-memory AirPack4 with configurable telemetry and read-back faults.

    ``airflow_factor`` is deliberately a simple model, not a physical claim:
    active airflow is ``percentage * factor`` and the extract side is 98% of
    that value.  This gives UI/integration tests a visible response to a
    confirmed setpoint while keeping the simulator explicit and replaceable.
    """

    def __init__(
        self,
        endpoint: TransportEndpoint | None = None,
        *,
        unit_id: int = 10,
        firmware: Sequence[int] = (4, 85, 16),
        serial_number: Sequence[int] = (0x007E, 0x00DF, 0x00C3, 0x001B, 0, 0),
        temperatures: Mapping[str, float | None] | None = None,
        mode: int = 0,
        season: int = 0,
        manual_fan_speed: int = 30,
        temporary_fan_speed: int = 40,
        special_mode: int = 0,
        power: bool = True,
        constant_flow_active: bool = True,
        airflow_factor: float = 6.0,
        response_delay_seconds: float = 0.0,
        readback_offset: int = 0,
    ) -> None:
        if not 1 <= unit_id <= 247:
            raise ValueError("unit_id must be in the range 1..247")
        if len(firmware) != 3 or any(not 0 <= int(part) <= 0xFFFF for part in firmware):
            raise ValueError("firmware must contain three uint16 values")
        if len(serial_number) != 6 or any(
            not 0 <= int(part) <= 0xFFFF for part in serial_number
        ):
            raise ValueError("serial_number must contain six uint16 values")
        if airflow_factor < 0 or response_delay_seconds < 0:
            raise ValueError("airflow factor and response delay cannot be negative")
        self.endpoint = endpoint or TransportEndpoint(
            TransportKind.SERIAL, "/dev/thessla-green-simulator"
        )
        self.unit_id = unit_id
        self.airflow_factor = airflow_factor
        self.response_delay_seconds = response_delay_seconds
        self.readback_offset = readback_offset
        self.constant_flow_active = constant_flow_active
        self.writes: list[tuple[int, int, int]] = []
        self.write_blocks: list[tuple[int, tuple[int, ...], int]] = []
        self._connected = False
        self._input_registers: dict[int, int] = {
            0: int(firmware[0]),
            1: int(firmware[1]),
            2: 0,
            3: 0,
            4: int(firmware[2]),
            **{
                16 + index: _encode_temperature(
                    (temperatures or {}).get(name, default)
                )
                for index, (name, default) in enumerate(
                    (
                        ("outdoor_temperature", 14.9),
                        ("supply_temperature", 22.3),
                        ("extract_temperature", 24.1),
                        ("fpx_temperature", 15.4),
                        ("duct_supply_temperature", None),
                        ("gwc_temperature", None),
                        ("ambient_temperature", 20.4),
                    )
                )
            },
            **{
                24 + index: int(value)
                for index, value in enumerate(serial_number)
            },
        }
        self._holding_registers: dict[int, int] = {
            4192: 1,
            4198: 1,
            4208: mode,
            4209: season,
            4210: manual_fan_speed,
            4211: temporary_fan_speed,
            4224: special_mode,
            4304: 0,
            4305: 0,
            4320: 0,
            4330: 0,
            4387: 1 if power else 0,
            4400: mode,
            4401: temporary_fan_speed,
            4402: 0,
            4704: 1,
            4711: 2,
        }
        self._validate_initial_registers()

    async def connect(self) -> None:
        self._connected = True

    async def close(self) -> None:
        self._connected = False

    async def read_input_registers(
        self, address: int, count: int, unit_id: int
    ) -> tuple[int, ...]:
        self._before_request(unit_id)
        await self._delay()
        if (address, count) == (256, 2):
            return self._airflow_registers()
        if (address, count) == (271, 5):
            supply, extract = self._target_flowrates()
            return (
                int(self.constant_flow_active),
                *self._active_percentages(),
                supply,
                extract,
            )
        if (address, count) == (272, 2):
            return self._active_percentages()
        return self._read_block(self._input_registers, address, count)

    async def read_holding_registers(
        self, address: int, count: int, unit_id: int
    ) -> tuple[int, ...]:
        self._before_request(unit_id)
        await self._delay()
        return self._read_block(self._holding_registers, address, count)

    async def read_coils(self, address: int, count: int, unit_id: int) -> tuple[bool, ...]:
        self._before_request(unit_id)
        await self._delay()
        return tuple(False for _ in range(count))

    async def read_discrete_inputs(
        self, address: int, count: int, unit_id: int
    ) -> tuple[bool, ...]:
        self._before_request(unit_id)
        await self._delay()
        return tuple(False for _ in range(count))

    async def write_holding_register(self, address: int, value: int, unit_id: int) -> None:
        self._before_request(unit_id)
        await self._delay()
        if not 0 <= value <= 0xFFFF:
            raise ValueError("holding register value must be uint16")
        if address not in self._holding_registers:
            raise ReadResponseError(f"simulator does not expose holding register {address}")
        self.writes.append((address, value, unit_id))
        self._holding_registers[address] = value + self.readback_offset

    async def write_holding_registers(
        self, address: int, values: Sequence[int], unit_id: int
    ) -> None:
        self._before_request(unit_id)
        await self._delay()
        normalized = tuple(int(value) for value in values)
        if not normalized:
            raise ValueError("at least one holding register value is required")
        if any(value < 0 or value > 0xFFFF for value in normalized):
            raise ValueError("holding register values must be uint16")
        if any(
            address + offset not in self._holding_registers
            for offset in range(len(normalized))
        ):
            raise ReadResponseError("simulator does not expose the complete holding register block")
        self.write_blocks.append((address, normalized, unit_id))
        for offset, value in enumerate(normalized):
            self._holding_registers[address + offset] = value + self.readback_offset
        if address == 4400 and len(normalized) == 3 and normalized[2] == 1:
            self._holding_registers[4208] = normalized[0] + self.readback_offset
            self._holding_registers[4211] = normalized[1] + self.readback_offset

    def _airflow_registers(self) -> tuple[int, int]:
        if not self.constant_flow_active:
            return (0xFFFF, 0xFFFF)
        if self._holding_registers[4387] == 0:
            return (0, 0)
        return self._target_flowrates()

    def _target_flowrates(self) -> tuple[int, int]:
        if self._holding_registers[4387] == 0:
            return (0, 0)
        speed = self._active_percentages()[0]
        supply = max(0, round(speed * self.airflow_factor))
        return supply, round(supply * 0.98)

    def _active_percentages(self) -> tuple[int, int]:
        if self._holding_registers[4387] == 0:
            return (0, 0)
        mode = self._holding_registers[4208]
        speed = self._holding_registers[4211] if mode == 2 else self._holding_registers[4210]
        return (speed, speed)

    @staticmethod
    def _read_block(registers: Mapping[int, int], address: int, count: int) -> tuple[int, ...]:
        if count < 1:
            raise ValueError("register count must be positive")
        try:
            return tuple(registers[address + offset] for offset in range(count))
        except KeyError as exc:
            raise ReadResponseError(
                f"simulator does not expose register {exc.args[0]}"
            ) from exc

    def _before_request(self, unit_id: int) -> None:
        if not self._connected:
            raise ModbusTransportError("simulated transport is not connected")
        if unit_id != self.unit_id:
            raise ReadResponseError(f"no simulated device at unit id {unit_id}")

    async def _delay(self) -> None:
        if self.response_delay_seconds:
            await asyncio.sleep(self.response_delay_seconds)

    def _validate_initial_registers(self) -> None:
        for address in (4208, 4209, 4224, 4304, 4320, 4387):
            value = self._holding_registers[address]
            if value < 0 or value > 1 and address in {4209, 4304, 4320, 4387}:
                raise ValueError(f"invalid initial value for holding register {address}")
        for address in (4210, 4211):
            if not 10 <= self._holding_registers[address] <= 100:
                raise ValueError(f"invalid initial fan speed at register {address}")
