"""Home Assistant adapter for a Thessla Green FastAPI gateway."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GatewayApi
from .const import CONF_TOKEN, CONF_URL
from .coordinator import ThesslaGreenCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.FAN,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
]


@dataclass(slots=True)
class RuntimeData:
    api: GatewayApi
    coordinator: ThesslaGreenCoordinator


type ThesslaGreenConfigEntry = ConfigEntry[RuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: ThesslaGreenConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    api = GatewayApi(
        session,
        entry.data[CONF_URL],
        entry.data.get(CONF_TOKEN),
    )
    coordinator = ThesslaGreenCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = RuntimeData(api=api, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ThesslaGreenConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
