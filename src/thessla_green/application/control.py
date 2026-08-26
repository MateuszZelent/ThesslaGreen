"""First safe control slice for AirPack fan speed and operating modes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum
from typing import Final

from thessla_green.domain.models import (
    AuditEvent,
    Capabilities,
    DeviceIdentity,
    TransportEndpoint,
)
from thessla_green.protocol.transport import ModbusTransport
from thessla_green.registers import REGISTERS_BY_KEY, RegisterDefinition


class DeviceControlError(RuntimeError):
    """Base class for a rejected or unconfirmed control operation."""


class UnsupportedControl(DeviceControlError):
    """Raised when a command is outside the verified control surface."""


class IdentityNotConfirmed(DeviceControlError):
    """Raised when control is attempted before a read-only fingerprint."""


class ControlVerificationError(DeviceControlError):
    """Raised when read-back does not confirm the requested value."""


class CommandConflict(DeviceControlError):
    """Raised when a command is stale or reuses an idempotency key differently."""


class AirPackMode(IntEnum):
    AUTOMATIC = 0
    MANUAL = 1
    TEMPORARY = 2


class SpecialMode(IntEnum):
    NONE = 0
    HOOD = 1
    FIREPLACE = 2
    AIRING_BUTTON = 3
    AIRING_SWITCH = 4
    AIRING_HUMIDITY = 5
    AIRING_AIR_QUALITY = 6
    AIRING_MANUAL = 7
    AIRING_AUTOMATIC = 8
    AIRING_SCHEDULE = 9
    OPEN_WINDOWS = 10
    EMPTY_HOUSE = 11


SPECIAL_MODE_NAMES: Final[dict[SpecialMode, str]] = {
    SpecialMode.NONE: "none",
    SpecialMode.HOOD: "hood",
    SpecialMode.FIREPLACE: "fireplace",
    SpecialMode.AIRING_BUTTON: "airing_button",
    SpecialMode.AIRING_SWITCH: "airing_switch",
    SpecialMode.AIRING_HUMIDITY: "airing_humidity",
    SpecialMode.AIRING_AIR_QUALITY: "airing_air_quality",
    SpecialMode.AIRING_MANUAL: "airing_manual",
    SpecialMode.AIRING_AUTOMATIC: "airing_automatic",
    SpecialMode.AIRING_SCHEDULE: "airing_schedule",
    SpecialMode.OPEN_WINDOWS: "open_windows",
    SpecialMode.EMPTY_HOUSE: "empty_house",
}

# Input-driven values remain decodable, but the UI must not pretend that a
# sensor or external switch can be safely simulated by an arbitrary write.
USER_SELECTABLE_SPECIAL_MODES: Final[dict[SpecialMode, str]] = {
    SpecialMode.NONE: "none",
    SpecialMode.HOOD: "hood",
    SpecialMode.FIREPLACE: "fireplace",
    SpecialMode.AIRING_MANUAL: "airing_manual",
    SpecialMode.OPEN_WINDOWS: "open_windows",
    SpecialMode.EMPTY_HOUSE: "empty_house",
}

DEFAULT_CONTROL_CAPABILITIES = Capabilities(
    features=frozenset(
        {
            "mode",
            "manual_fan_speed",
            "temporary_fan_speed",
            "special_mode",
            "on_off",
        }
    ),
    min_fan_percentage=10,
    max_fan_percentage=100,
)


@dataclass(frozen=True, slots=True)
class ControlResult:
    """Confirmed result of one serialized write/read-back operation."""

    command: str
    register: str
    address: int
    requested_value: int
    confirmed_value: int
    endpoint: TransportEndpoint
    unit_id: int
    source: str = "unknown"
    audit_sequence: int | None = None

    @property
    def confirmed(self) -> bool:
        return self.requested_value == self.confirmed_value

    def to_dict(self) -> dict[str, object]:
        return {
            "command": self.command,
            "register": self.register,
            "address": self.address,
            "requested_value": self.requested_value,
            "confirmed_value": self.confirmed_value,
            "confirmed": self.confirmed,
            "endpoint": self.endpoint.to_dict(),
            "unit_id": self.unit_id,
            "source": self.source,
            "audit_sequence": self.audit_sequence,
        }


class AirPackController:
    """Own the write lock and expose typed, documented control operations.

    The caller owns the transport lifecycle. This class never scans, changes
    access level, or writes an unlisted register.
    """

    def __init__(
        self,
        transport: ModbusTransport,
        *,
        endpoint: TransportEndpoint,
        unit_id: int,
        identity: DeviceIdentity | None = None,
        capabilities: Capabilities | None = None,
    ) -> None:
        if not 1 <= unit_id <= 247:
            raise ValueError("unit_id must be in the range 1..247")
        self.transport = transport
        self.endpoint = endpoint
        self.unit_id = unit_id
        self.identity = identity
        self.capabilities = (
            capabilities if capabilities is not None else DEFAULT_CONTROL_CAPABILITIES
        )
        self._write_lock = asyncio.Lock()
        self._audit_events: list[AuditEvent] = []

    @property
    def audit_events(self) -> tuple[AuditEvent, ...]:
        """Return immutable in-memory write evidence in execution order."""

        return tuple(self._audit_events)

    def _record_audit(
        self,
        *,
        source: str,
        command: str,
        register: RegisterDefinition,
        requested_value: int,
        confirmed_value: int | None,
        success: bool,
        error: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            sequence=len(self._audit_events) + 1,
            captured_at=datetime.now(UTC),
            source=source.strip() or "unknown",
            command=command,
            register=register.key,
            address=register.address,
            requested_value=requested_value,
            confirmed_value=confirmed_value,
            success=success,
            endpoint=self.endpoint,
            unit_id=self.unit_id,
            error=error,
        )
        self._audit_events.append(event)
        return event

    async def _write_and_confirm(
        self,
        register: RegisterDefinition,
        value: int,
        *,
        command: str,
        feature: str,
        source: str = "unknown",
    ) -> ControlResult:
        if self.identity is None:
            raise IdentityNotConfirmed(
                "read and confirm the AirPack identity before enabling control"
            )
        if not self.capabilities.supports(feature):
            raise UnsupportedControl(f"device does not advertise capability {feature}")
        if not register.writable:
            raise UnsupportedControl(f"register {register.key} is read-only")
        if register.minimum is not None and value < register.minimum:
            raise ValueError(f"{register.key} must be >= {register.minimum}")
        if register.maximum is not None and value > register.maximum:
            raise ValueError(f"{register.key} must be <= {register.maximum}")

        async with self._write_lock:
            confirmed_value: int | None = None
            try:
                await self.transport.write_holding_register(register.address, value, self.unit_id)
                values = await self.transport.read_holding_registers(
                    register.address, 1, self.unit_id
                )
                if len(values) != 1:
                    raise ControlVerificationError(
                        f"read-back for {register.key} returned {len(values)} values"
                    )
                confirmed_value = int(values[0])
                if confirmed_value != value:
                    raise ControlVerificationError(
                        f"read-back for {register.key} returned {confirmed_value}, expected {value}"
                    )
            except Exception as exc:
                self._record_audit(
                    source=source,
                    command=command,
                    register=register,
                    requested_value=value,
                    confirmed_value=confirmed_value,
                    success=False,
                    error=str(exc),
                )
                raise

            event = self._record_audit(
                source=source,
                command=command,
                register=register,
                requested_value=value,
                confirmed_value=confirmed_value,
                success=True,
            )
            return ControlResult(
                command=command,
                register=register.key,
                address=register.address,
                requested_value=value,
                confirmed_value=confirmed_value,
                endpoint=self.endpoint,
                unit_id=self.unit_id,
                source=source.strip() or "unknown",
                audit_sequence=event.sequence,
            )

    async def set_fan_speed(self, percentage: int, *, source: str = "unknown") -> ControlResult:
        """Set the documented manual fan intensity (10..100%)."""

        return await self._write_and_confirm(
            REGISTERS_BY_KEY["manual_fan_speed"],
            percentage,
            command="set_fan_speed",
            feature="manual_fan_speed",
            source=source,
        )

    async def set_temporary_fan_speed(
        self, percentage: int, *, source: str = "unknown"
    ) -> ControlResult:
        """Store the documented temporary-mode fan intensity (10..100%).

        This does not activate the temporary timer. AirPack4 requires the
        dedicated three-register atomic operation implemented by
        :meth:`activate_temporary_mode` for that transition.
        """

        return await self._write_and_confirm(
            REGISTERS_BY_KEY["temporary_fan_speed"],
            percentage,
            command="set_temporary_fan_speed",
            feature="temporary_fan_speed",
            source=source,
        )

    async def activate_temporary_mode(
        self, percentage: int, *, source: str = "unknown"
    ) -> ControlResult:
        """Atomically activate temporary mode with the requested airflow.

        The vendor protocol requires one function-16 write containing
        ``[mode=2, airflow, activation_flag=1]`` at 4400..4402. The duration
        is an Air++/controller setting and is not exposed by the public
        AirPack4 Modbus map.
        """

        register = REGISTERS_BY_KEY["temporary_activation_speed"]
        if self.identity is None:
            raise IdentityNotConfirmed(
                "read and confirm the AirPack identity before enabling control"
            )
        for feature in ("mode", "temporary_fan_speed"):
            if not self.capabilities.supports(feature):
                raise UnsupportedControl(f"device does not advertise capability {feature}")
        if isinstance(percentage, bool) or not isinstance(percentage, int):
            raise TypeError("temporary fan speed must be an integer")
        if not 10 <= percentage <= 100:
            raise ValueError("temporary fan speed must be in the range 10..100")

        command = "activate_temporary_mode"
        async with self._write_lock:
            confirmed_value: int | None = None
            try:
                await self.transport.write_holding_registers(
                    REGISTERS_BY_KEY["temporary_activation_mode"].address,
                    (int(AirPackMode.TEMPORARY), percentage, 1),
                    self.unit_id,
                )
                mode_block = await self.transport.read_holding_registers(
                    REGISTERS_BY_KEY["mode"].address,
                    4,
                    self.unit_id,
                )
                if len(mode_block) != 4:
                    raise ControlVerificationError(
                        f"temporary-mode read-back returned {len(mode_block)} values"
                    )
                confirmed_mode = int(mode_block[0])
                confirmed_value = int(mode_block[3])
                if confirmed_mode != int(AirPackMode.TEMPORARY):
                    raise ControlVerificationError(
                        "temporary-mode read-back did not confirm mode 2: "
                        f"received {confirmed_mode}"
                    )
                if confirmed_value != percentage:
                    raise ControlVerificationError(
                        "temporary airflow read-back returned "
                        f"{confirmed_value}, expected {percentage}"
                    )
            except Exception as exc:
                self._record_audit(
                    source=source,
                    command=command,
                    register=register,
                    requested_value=percentage,
                    confirmed_value=confirmed_value,
                    success=False,
                    error=str(exc),
                )
                raise

            event = self._record_audit(
                source=source,
                command=command,
                register=register,
                requested_value=percentage,
                confirmed_value=confirmed_value,
                success=True,
            )
            return ControlResult(
                command=command,
                register=register.key,
                address=register.address,
                requested_value=percentage,
                confirmed_value=confirmed_value,
                endpoint=self.endpoint,
                unit_id=self.unit_id,
                source=source.strip() or "unknown",
                audit_sequence=event.sequence,
            )

    async def set_mode(
        self, mode: AirPackMode | int, *, source: str = "unknown"
    ) -> ControlResult:
        try:
            selected = AirPackMode(mode)
        except ValueError as exc:
            raise ValueError("mode must be 0 (automatic), 1 (manual), or 2 (temporary)") from exc
        if selected is AirPackMode.TEMPORARY:
            raise ValueError(
                "temporary mode requires activate_temporary_mode with an airflow percentage"
            )
        return await self._write_and_confirm(
            REGISTERS_BY_KEY["mode"],
            int(selected),
            command=f"set_mode:{selected.name.lower()}",
            feature="mode",
            source=source,
        )

    async def set_special_mode(
        self, mode: SpecialMode | int, *, source: str = "unknown"
    ) -> ControlResult:
        try:
            selected = SpecialMode(mode)
        except ValueError as exc:
            raise ValueError("unsupported AirPack special mode") from exc
        return await self._write_and_confirm(
            REGISTERS_BY_KEY["special_mode"],
            int(selected),
            command=f"set_special_mode:{SPECIAL_MODE_NAMES[selected]}",
            feature="special_mode",
            source=source,
        )

    async def set_fireplace(
        self, enabled: bool = True, *, source: str = "unknown"
    ) -> ControlResult:
        return await self.set_special_mode(
            SpecialMode.FIREPLACE if enabled else SpecialMode.NONE, source=source
        )

    async def set_airing(self, enabled: bool = True, *, source: str = "unknown") -> ControlResult:
        return await self.set_special_mode(
            SpecialMode.AIRING_MANUAL if enabled else SpecialMode.NONE, source=source
        )

    async def set_open_windows(
        self, enabled: bool = True, *, source: str = "unknown"
    ) -> ControlResult:
        return await self.set_special_mode(
            SpecialMode.OPEN_WINDOWS if enabled else SpecialMode.NONE, source=source
        )

    async def set_empty_house(
        self, enabled: bool = True, *, source: str = "unknown"
    ) -> ControlResult:
        return await self.set_special_mode(
            SpecialMode.EMPTY_HOUSE if enabled else SpecialMode.NONE, source=source
        )

    async def set_power(self, enabled: bool, *, source: str = "unknown") -> ControlResult:
        return await self._write_and_confirm(
            REGISTERS_BY_KEY["on_off_panel_mode"],
            1 if enabled else 0,
            command="set_power",
            feature="on_off",
            source=source,
        )
