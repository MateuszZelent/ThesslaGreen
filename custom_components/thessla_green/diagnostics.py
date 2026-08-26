"""Redacted diagnostics for troubleshooting the gateway adapter."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_BAUDRATE,
    CONF_CONNECTION_TYPE,
    CONF_SERIAL_PORT,
    CONF_TIMEOUT,
    CONF_TOKEN,
    CONF_UNIT_ID,
    CONF_URL,
    CONNECTION_GATEWAY,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    runtime = entry.runtime_data
    state = runtime.coordinator.data or {}
    connection_type = entry.data.get(CONF_CONNECTION_TYPE)
    if connection_type is None:
        connection_type = CONNECTION_GATEWAY if CONF_URL in entry.data else "direct"
    config = {"connection_type": connection_type}
    if connection_type == CONNECTION_GATEWAY:
        config.update(
            url=entry.data.get(CONF_URL),
            token_configured=bool(entry.data.get(CONF_TOKEN)),
        )
    else:
        config.update(
            serial_port=entry.data.get(CONF_SERIAL_PORT),
            unit_id=entry.data.get(CONF_UNIT_ID),
            baudrate=entry.data.get(CONF_BAUDRATE),
            timeout=entry.data.get(CONF_TIMEOUT),
        )
    return {
        "config": config,
        "state": state,
        "capabilities": runtime.coordinator.capabilities,
        "control_options": runtime.coordinator.control_options,
    }
