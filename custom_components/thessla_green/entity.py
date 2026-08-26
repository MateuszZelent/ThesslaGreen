"""Shared Home Assistant entity helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ThesslaGreenCoordinator


class ThesslaGreenEntity(CoordinatorEntity[ThesslaGreenCoordinator]):
    """Base entity backed by one gateway snapshot."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ThesslaGreenCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{self._stable_id}_{key}"

    @property
    def _stable_id(self) -> str:
        identity = self.coordinator.data.get("identity", {}) if self.coordinator.data else {}
        if isinstance(identity, Mapping) and identity.get("stable_id"):
            return str(identity["stable_id"])
        return self.coordinator.config_entry.entry_id

    @property
    def device_info(self) -> DeviceInfo:
        identity = self.coordinator.data.get("identity", {}) if self.coordinator.data else {}
        identity = identity if isinstance(identity, Mapping) else {}
        stable_id = str(identity.get("stable_id") or self.coordinator.config_entry.entry_id)
        return DeviceInfo(
            identifiers={(DOMAIN, stable_id)},
            name=str(identity.get("model") or "Thessla Green"),
            manufacturer="Thessla Green",
            model=str(identity.get("model") or "AirPack4"),
            serial_number=identity.get("serial_number"),
            sw_version=identity.get("firmware"),
        )

    @property
    def available(self) -> bool:
        data: Mapping[str, Any] = self.coordinator.data or {}
        return self.coordinator.last_update_success and data.get("online") is True

    @property
    def values(self) -> Mapping[str, Any]:
        data: Mapping[str, Any] = self.coordinator.data or {}
        values = data.get("values", {})
        return values if isinstance(values, Mapping) else {}

    async def async_send_command(self, command_type: str, **parameters: object) -> None:
        await self.coordinator.async_send_command(command_type, parameters)
