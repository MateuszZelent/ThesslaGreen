"""Redacted diagnostics for troubleshooting the gateway adapter."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN, CONF_URL


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    runtime = entry.runtime_data
    state = runtime.coordinator.data or {}
    return {
        "config": {
            "url": entry.data.get(CONF_URL),
            "token_configured": bool(entry.data.get(CONF_TOKEN)),
        },
        "state": state,
        "capabilities": runtime.coordinator.capabilities,
        "control_options": runtime.coordinator.control_options,
    }
