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
    async_add_entities([ThesslaGreenConnectivitySensor(entry.runtime_data.coordinator)])


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
