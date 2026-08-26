"""Connectivity diagnostics exposed as a Home Assistant binary sensor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .entity import ThesslaGreenEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            ThesslaGreenConnectivitySensor(coordinator),
            ThesslaGreenBypassSensor(coordinator),
            ThesslaGreenFpxSensor(coordinator),
            ThesslaGreenErvPostHeaterSensor(coordinator),
        ]
    )


class ThesslaGreenConnectivitySensor(ThesslaGreenEntity, BinarySensorEntity):
    """Whether the selected gateway currently reports an online AirPack."""

    _attr_name = "Połączenie z centralą"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "connectivity")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        return bool(data.get("online"))


class ThesslaGreenBypassSensor(ThesslaGreenEntity, BinarySensorEntity):
    """Physical bypass actuator state reported by coil 9."""

    _attr_name = "Klapa bypassu"
    _attr_device_class = BinarySensorDeviceClass.OPENING

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "bypass_actuator_open")

    @property
    def available(self) -> bool:
        return super().available and self.values.get("bypass_actuator_open") is not None

    @property
    def is_on(self) -> bool:
        return self.values.get("bypass_actuator_open") is True


class ThesslaGreenFpxSensor(ThesslaGreenEntity, BinarySensorEntity):
    """FPX anti-freeze system state; the stage is exposed as an attribute."""

    _attr_name = "System FPX"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "fpx_system_active")

    @property
    def available(self) -> bool:
        return super().available and self.values.get("fpx_system_active") is not None

    @property
    def is_on(self) -> bool:
        return self.values.get("fpx_system_active") is True

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {
            "stage": self.values.get("fpx_stage"),
            "outdoor_temperature": self.values.get("outdoor_temperature"),
            "fpx_temperature": self.values.get("fpx_temperature"),
        }


class ThesslaGreenErvPostHeaterSensor(ThesslaGreenEntity, BinarySensorEntity):
    """Actual built-in ERV post-heater state reported by postHeater_on."""

    _attr_name = "Nagrzewnica wtórna ERV"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "erv_post_heater_active")

    @property
    def available(self) -> bool:
        return super().available and self.values.get("erv_post_heater_active") is not None

    @property
    def is_on(self) -> bool:
        return self.values.get("erv_post_heater_active") is True

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {
            "mode": self.values.get("erv_post_heater_mode"),
            "supply_temperature": self.values.get("supply_temperature"),
        }
