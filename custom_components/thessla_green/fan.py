"""Native Home Assistant fan entity for AirPack control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import SPECIAL_MODE_NAMES, SPECIAL_MODE_OPTIONS
from .entity import ThesslaGreenEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    async_add_entities([ThesslaGreenFan(entry.runtime_data.coordinator)])


class ThesslaGreenFan(ThesslaGreenEntity, FanEntity):
    """Fan speed and safe special-mode commands mapped to one entity."""

    _attr_name = "Rekuperator"
    _attr_supported_features = FanEntityFeature.SET_SPEED | FanEntityFeature.PRESET_MODE
    _attr_percentage_step = 1

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "fan")

    @property
    def is_on(self) -> bool | None:
        value = self.values.get("power")
        return None if value is None else bool(value)

    @property
    def percentage(self) -> int | None:
        # Home Assistant accepts only one 0..100 control percentage, while the
        # AirPack can demand asymmetric values up to 150% in automatic/special
        # operation. Do not misrepresent that state as one fan percentage;
        # exact supply/extract demand remains available through two sensors.
        mode = self.values.get("mode")
        if mode == 0:
            return None
        speed_key = "temporary_fan_speed" if mode == 2 else "manual_fan_speed"
        value = self.values.get(speed_key)
        return None if value is None else int(value)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose setpoints, measured airflow and the last read-back result."""

        attributes: dict[str, object] = {
            "manual_setpoint_percentage": self.values.get("manual_fan_speed"),
            "temporary_setpoint_percentage": self.values.get("temporary_fan_speed"),
            "supply_demand_percentage": self.values.get("supply_percentage"),
            "extract_demand_percentage": self.values.get("extract_percentage"),
            "constant_flow_available": self.values.get("constant_flow_available"),
            "supply_airflow_m3h": self.values.get("supply_airflow"),
            "extract_airflow_m3h": self.values.get("extract_airflow"),
            "supply_flowrate_m3h": self.values.get("supply_flowrate"),
            "extract_flowrate_m3h": self.values.get("extract_flowrate"),
            "last_command": self.coordinator.last_command,
        }
        return attributes

    @property
    def preset_modes(self) -> list[str]:
        configured = self.coordinator.control_options.get("special_modes")
        if isinstance(configured, dict) and configured:
            return [str(name) for name in configured]
        return list(SPECIAL_MODE_OPTIONS)

    @property
    def preset_mode(self) -> str | None:
        value = self.values.get("special_mode")
        try:
            name = SPECIAL_MODE_NAMES[int(value)]
        except (KeyError, TypeError, ValueError):
            return None
        return name if name in self.preset_modes else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.async_send_command("set_power", enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_send_command("set_power", enabled=False)

    async def async_set_percentage(self, percentage: int) -> None:
        # In temporary mode the slider edits the temporary setpoint. In every
        # other mode it explicitly selects manual mode before changing 4210.
        if self.values.get("mode") == 2:
            await self.async_send_command("activate_temporary_mode", percentage=percentage)
        else:
            await self.async_send_command("set_mode", mode="manual")
            await self.async_send_command("set_fan_speed", percentage=percentage)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in self.preset_modes:
            raise ValueError(f"unsupported special mode: {preset_mode}")
        await self.async_send_command("set_special_mode", mode=preset_mode)
