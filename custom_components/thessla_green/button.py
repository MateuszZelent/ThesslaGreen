"""Safe momentary actions exposed by the integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .entity import ThesslaGreenEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    async_add_entities([ThesslaGreenClearSpecialModeButton(entry.runtime_data.coordinator)])


class ThesslaGreenClearSpecialModeButton(ThesslaGreenEntity, ButtonEntity):
    """Clear a currently selected special mode without exposing raw registers."""

    _attr_name = "Wyłącz tryb specjalny"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "clear_special_mode")

    async def async_press(self) -> None:
        await self.async_send_command("set_special_mode", mode="none")
