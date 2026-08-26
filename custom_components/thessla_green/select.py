"""Select entities for operating and special modes."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    MODE_LABELS,
    MODE_NAMES,
    MODE_OPTIONS,
    SPECIAL_MODE_LABELS,
    SPECIAL_MODE_NAMES,
    SPECIAL_MODE_OPTIONS,
)
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
    _attr_options = list(MODE_LABELS.values())

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "mode")

    @property
    def current_option(self) -> str | None:
        try:
            raw_mode = MODE_NAMES[int(self.values["mode"])]
            return MODE_LABELS.get(raw_mode, raw_mode)
        except (KeyError, TypeError, ValueError):
            return None

    async def async_select_option(self, option: str) -> None:
        raw_option = next((name for name, label in MODE_LABELS.items() if label == option), option)
        if raw_option not in MODE_OPTIONS:
            raise ValueError(f"unsupported operating mode: {option}")
        if raw_option == "temporary":
            percentage = self.values.get("temporary_fan_speed")
            if not isinstance(percentage, (int, float)) or isinstance(percentage, bool):
                raise ValueError("temporary fan speed is unavailable")
            await self.async_send_command("activate_temporary_mode", percentage=int(percentage))
            return
        await self.async_send_command("set_mode", mode=raw_option)


class ThesslaGreenSpecialModeSelect(ThesslaGreenEntity, SelectEntity):
    """Documented AirPack special modes."""

    _attr_name = "Tryb specjalny"
    _attr_options = [SPECIAL_MODE_LABELS.get(name, name) for name in SPECIAL_MODE_OPTIONS]

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "special_mode")

    @property
    def current_option(self) -> str | None:
        try:
            name = SPECIAL_MODE_NAMES[int(self.values["special_mode"])]
        except (KeyError, TypeError, ValueError):
            return None
        label = SPECIAL_MODE_LABELS.get(name, name)
        return label if label in self.options else None

    async def async_select_option(self, option: str) -> None:
        raw_option = next(
            (name for name, label in SPECIAL_MODE_LABELS.items() if label == option), option
        )
        if raw_option not in SPECIAL_MODE_OPTIONS:
            raise ValueError(f"unsupported special mode: {option}")
        await self.async_send_command("set_special_mode", mode=raw_option)
