"""Select entities for operating and special modes."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import MODE_NAMES, MODE_OPTIONS, SPECIAL_MODE_NAMES, SPECIAL_MODE_OPTIONS
from .entity import ThesslaGreenEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            ThesslaGreenModeSelect(coordinator),
            ThesslaGreenSpecialModeSelect(coordinator),
        ]
    )


class ThesslaGreenModeSelect(ThesslaGreenEntity, SelectEntity):
    """Automatic/manual/temporary operating mode."""

    _attr_name = "Tryb pracy"
    _attr_options = list(MODE_OPTIONS)

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "mode")

    @property
    def current_option(self) -> str | None:
        try:
            return MODE_NAMES[int(self.values["mode"])]
        except (KeyError, TypeError, ValueError):
            return None

    async def async_select_option(self, option: str) -> None:
        if option not in MODE_OPTIONS:
            raise ValueError(f"unsupported operating mode: {option}")
        await self.async_send_command("set_mode", mode=option)


class ThesslaGreenSpecialModeSelect(ThesslaGreenEntity, SelectEntity):
    """Documented AirPack special modes."""

    _attr_name = "Tryb specjalny"
    _attr_options = list(SPECIAL_MODE_OPTIONS)

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "special_mode")

    @property
    def current_option(self) -> str | None:
        try:
            name = SPECIAL_MODE_NAMES[int(self.values["special_mode"])]
        except (KeyError, TypeError, ValueError):
            return None
        return name if name in self.options else None

    async def async_select_option(self, option: str) -> None:
        if option not in SPECIAL_MODE_OPTIONS:
            raise ValueError(f"unsupported special mode: {option}")
        await self.async_send_command("set_special_mode", mode=option)
