"""Authenticated Home Assistant HTTP bridge for the bundled direct-mode UI."""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from aiohttp import web
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import DOMAIN


def _runtime(request: web.Request, entry_id: str) -> Any:
    hass = request.app[KEY_HASS]
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
        raise web.HTTPNotFound(text="Thessla Green entry not found")
    return entry.runtime_data


class ThesslaGreenStateView(HomeAssistantView):
    url = "/api/thessla_green/{entry_id}/state"
    name = "api:thessla_green:state"
    requires_auth = True

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        runtime = _runtime(request, entry_id)
        return self.json(runtime.coordinator.data or {})


class ThesslaGreenOptionsView(HomeAssistantView):
    url = "/api/thessla_green/{entry_id}/control/options"
    name = "api:thessla_green:control-options"
    requires_auth = True

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        runtime = _runtime(request, entry_id)
        return self.json(runtime.coordinator.control_options)


class ThesslaGreenSerialPortsView(HomeAssistantView):
    url = "/api/thessla_green/{entry_id}/discovery/serial-ports"
    name = "api:thessla_green:serial-ports"
    requires_auth = True

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        runtime = _runtime(request, entry_id)
        ports = await runtime.api.async_get_serial_ports()
        return self.json(ports)


class ThesslaGreenCommandView(HomeAssistantView):
    url = "/api/thessla_green/{entry_id}/commands"
    name = "api:thessla_green:commands"
    requires_auth = True

    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        runtime = _runtime(request, entry_id)
        try:
            payload = await request.json()
        except ValueError:
            return self.json_message("Invalid JSON", HTTPStatus.BAD_REQUEST)
        if not isinstance(payload, Mapping):
            return self.json_message("Command must be a JSON object", HTTPStatus.BAD_REQUEST)
        command_type = payload.get("type")
        parameters = payload.get("parameters", {})
        if not isinstance(command_type, str) or not isinstance(parameters, Mapping):
            return self.json_message(
                "Command type and parameters are required", HTTPStatus.BAD_REQUEST
            )
        try:
            response = await runtime.coordinator.async_send_command(
                command_type,
                {str(key): value for key, value in parameters.items()},
            )
        except UpdateFailed as exc:
            return self.json_message(str(exc), HTTPStatus.CONFLICT)
        return self.json(response)


VIEWS = (
    ThesslaGreenStateView,
    ThesslaGreenOptionsView,
    ThesslaGreenSerialPortsView,
    ThesslaGreenCommandView,
)
