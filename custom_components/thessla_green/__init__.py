"""Home Assistant adapter for direct Modbus or an external gateway."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ._core.domain.models import TransportEndpoint, TransportKind
from .api import GatewayApi
from .const import (
    CONF_BAUDRATE,
    CONF_CONNECTION_TYPE,
    CONF_SERIAL_PORT,
    CONF_TIMEOUT,
    CONF_TOKEN,
    CONF_UNIT_ID,
    CONF_URL,
    CONNECTION_DIRECT,
    CONNECTION_GATEWAY,
    DEFAULT_BAUDRATE,
    DEFAULT_TIMEOUT,
    DEFAULT_UNIT_ID,
    DOMAIN,
)
from .coordinator import ThesslaGreenCoordinator
from .direct import DirectModbusApi
from .http import VIEWS

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
    api: GatewayApi | DirectModbusApi
    coordinator: ThesslaGreenCoordinator


type ThesslaGreenConfigEntry = ConfigEntry[RuntimeData]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register the authenticated API used by the bundled direct-mode panel."""

    for view in VIEWS:
        hass.http.register_view(view)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Mark pre-0.3 HTTP-only entries explicitly as external gateway mode."""

    if entry.version == 1:
        data = dict(entry.data)
        data.setdefault(CONF_CONNECTION_TYPE, CONNECTION_GATEWAY)
        hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True


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
                    "connection_type": _connection_type(entry),
                    "gateway_url": str(entry.data.get(CONF_URL, "")),
                    "entry_id": entry.entry_id,
                    "title": title,
                },
            }
        },
        require_admin=False,
        update=True,
    )
    integration_data.setdefault("panels", set()).add(panel_path)


async def async_setup_entry(hass: HomeAssistant, entry: ThesslaGreenConfigEntry) -> bool:
    if _connection_type(entry) == CONNECTION_DIRECT:
        endpoint = TransportEndpoint(
            TransportKind.SERIAL,
            str(entry.data[CONF_SERIAL_PORT]),
            baudrate=int(entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)),
            timeout_seconds=float(entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
        )
        api: GatewayApi | DirectModbusApi = DirectModbusApi(
            endpoint,
            int(entry.data.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)),
        )
    else:
        session = async_get_clientsession(hass)
        api = GatewayApi(
            session,
            entry.data[CONF_URL],
            entry.data.get(CONF_TOKEN),
        )
    try:
        await api.async_start()
    except Exception as exc:
        await api.async_close()
        raise ConfigEntryNotReady(str(exc)) from exc
    coordinator = ThesslaGreenCoordinator(hass, entry, api)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await api.async_close()
        raise
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
    if unloaded:
        await entry.runtime_data.api.async_close()
    try:
        from homeassistant.components import frontend

        frontend.async_remove_panel(hass, _panel_url_path(entry), warn_if_unknown=False)
    except (ImportError, RuntimeError, ValueError) as exc:
        _LOGGER.debug("Unable to remove the Thessla Green sidebar panel: %s", exc)
    return unloaded


def _connection_type(entry: ConfigEntry) -> str:
    """Keep entries created before direct mode working as gateway entries."""

    configured = entry.data.get(CONF_CONNECTION_TYPE)
    if configured in {CONNECTION_DIRECT, CONNECTION_GATEWAY}:
        return str(configured)
    return CONNECTION_GATEWAY if CONF_URL in entry.data else CONNECTION_DIRECT
