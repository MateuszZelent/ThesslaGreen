"""Home Assistant adapter for a Thessla Green FastAPI gateway."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GatewayApi
from .const import CONF_TOKEN, CONF_URL, DOMAIN
from .coordinator import ThesslaGreenCoordinator

_LOGGER = logging.getLogger(__name__)
_FRONTEND_URL = "/api/thessla_green/frontend"
_PANEL_PREFIX = "thessla-green"

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


def _panel_url_path(entry: ConfigEntry) -> str:
    """Return a stable, collision-resistant sidebar path for one config entry."""

    entry_id = str(entry.entry_id).replace("-", "")
    return f"{_PANEL_PREFIX}-{entry_id[:12]}"


async def _async_register_frontend_panel(
    hass: HomeAssistant,
    entry: ThesslaGreenConfigEntry,
    title: str,
) -> None:
    """Serve and register the panel that embeds the gateway's public UI."""

    from homeassistant.components import frontend
    from homeassistant.components.http import StaticPathConfig

    integration_data: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    if not integration_data.get("frontend_static_registered"):
        frontend_dir = Path(__file__).parent / "www"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(_FRONTEND_URL, str(frontend_dir), cache_headers=False)]
        )
        integration_data["frontend_static_registered"] = True

    panel_path = _panel_url_path(entry)
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=title,
        sidebar_icon="mdi:air-filter",
        frontend_url_path=panel_path,
        config={
            "_panel_custom": {
                "name": "thessla-green-panel",
                "module_url": f"{_FRONTEND_URL}/panel.js",
                "embed_iframe": False,
                "trust_external": False,
                "config": {
                    "gateway_url": str(entry.data[CONF_URL]),
                    "title": title,
                },
            }
        },
        require_admin=False,
        update=True,
    )
    integration_data.setdefault("panels", set()).add(panel_path)


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
    try:
        await _async_register_frontend_panel(hass, entry, "Thessla Green")
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        # Native entities remain useful when a minimal HA installation has no
        # frontend panel support; do not make the data path unavailable.
        _LOGGER.warning("Unable to register the Thessla Green sidebar panel: %s", exc)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ThesslaGreenConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    try:
        from homeassistant.components import frontend

        frontend.async_remove_panel(hass, _panel_url_path(entry), warn_if_unknown=False)
    except (ImportError, RuntimeError, ValueError) as exc:
        _LOGGER.debug("Unable to remove the Thessla Green sidebar panel: %s", exc)
    return unloaded
