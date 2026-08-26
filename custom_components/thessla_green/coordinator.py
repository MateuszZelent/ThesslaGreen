"""One coordinated polling loop for all Home Assistant entities."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GatewayApi, GatewayAuthError, GatewayError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class ThesslaGreenCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch one complete gateway snapshot for every entity platform."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: GatewayApi,
        *,
        update_interval: timedelta = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=update_interval,
            always_update=False,
        )
        self.api = api
        self.capabilities: dict[str, Any] = {}
        self.control_options: dict[str, Any] = {}
        self.last_command: dict[str, Any] | None = None

    async def _async_setup(self) -> None:
        try:
            self.capabilities = await self.api.async_get_capabilities()
            self.control_options = await self.api.async_get_control_options()
        except GatewayAuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except GatewayError as exc:
            raise UpdateFailed(str(exc)) from exc

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.api.async_get_state()
        except GatewayAuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except GatewayError as exc:
            raise UpdateFailed(str(exc)) from exc

    async def async_send_command(
        self,
        command_type: str,
        parameters: dict[str, object],
    ) -> dict[str, Any]:
        """Send one typed command and immediately publish confirmed state."""

        current = self.data or {}
        revision = current.get("revision") if isinstance(current, dict) else None
        expected_revision = (
            revision if isinstance(revision, int) and not isinstance(revision, bool) else None
        )
        try:
            response = await self.api.async_command(
                command_type,
                parameters,
                expected_revision=expected_revision,
            )
        except GatewayAuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except GatewayError as exc:
            raise UpdateFailed(str(exc)) from exc
        state = response.get("state")
        result = response.get("result")
        self.last_command = dict(result) if isinstance(result, dict) else None
        if isinstance(state, dict):
            self.async_set_updated_data(state)
        else:
            await self.async_request_refresh()
        return response
