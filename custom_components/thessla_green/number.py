"""Writable AirPack ventilation setpoints for automations and scenes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant

from .entity import ThesslaGreenEntity


@dataclass(frozen=True, slots=True)
class NumberSpec:
    """Describe one documented, writable percentage setpoint."""

    key: str
    name: str
    command: str


NUMBER_SPECS = (
    NumberSpec("manual_fan_speed", "Nastawa ręczna wentylacji", "set_fan_speed"),
    NumberSpec(
        "temporary_fan_speed",
        "Nastawa chwilowa wentylacji",
        "set_temporary_fan_speed",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Create setpoint entities backed by the shared coordinator snapshot."""

    coordinator = entry.runtime_data.coordinator
    async_add_entities(ThesslaGreenSetpointNumber(coordinator, spec) for spec in NUMBER_SPECS)


class ThesslaGreenSetpointNumber(ThesslaGreenEntity, NumberEntity):
    """One documented setpoint; changing it does not silently change mode."""

    _attr_native_min_value = 10
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, spec: NumberSpec) -> None:
        super().__init__(coordinator, spec.key)
        self.spec = spec
        self._attr_name = spec.name

    @property
    def native_value(self) -> float | None:
        """Return the setpoint confirmed by the controller read-back."""

        value = self.values.get(self.spec.key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        return float(value)

    async def async_set_native_value(self, value: float) -> None:
        """Write the typed setpoint command and publish confirmed state."""

        percentage = round(value)
        if percentage < self.native_min_value or percentage > self.native_max_value:
            raise ValueError(f"ventilation percentage is outside 10..100: {value}")
        command = self.spec.command
        # Scene entity order is not guaranteed. If Temporary mode was restored
        # before this Number entity, repeat the documented atomic activation
        # block so the newly requested percentage becomes active immediately.
        if self.spec.key == "temporary_fan_speed" and self.values.get("mode") == 2:
            command = "activate_temporary_mode"
        await self.async_send_command(command, percentage=percentage)
