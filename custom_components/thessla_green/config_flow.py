"""UI setup for a selected local FastAPI gateway."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GatewayApi, GatewayAuthError, GatewayError
from .const import CONF_TOKEN, CONF_URL, DEFAULT_URL, DOMAIN


def _format_discovery_details(
    state: Mapping[str, Any], serial_ports: Mapping[str, Any]
) -> dict[str, str]:
    """Turn the gateway discovery response into safe config-flow placeholders."""

    identity = state.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    endpoint = identity.get("endpoint")
    endpoint = endpoint if isinstance(endpoint, Mapping) else {}

    endpoint_text = str(endpoint.get("key") or endpoint.get("address") or "brak")
    port_items = serial_ports.get("ports")
    port_lines: list[str] = []
    if isinstance(port_items, list):
        for item in port_items:
            if not isinstance(item, Mapping):
                continue
            device = str(item.get("device") or "")
            description = str(item.get("description") or "").strip()
            if device:
                port_lines.append(f"{device} ({description})" if description else device)

    return {
        "model": str(identity.get("model") or "AirPack"),
        "firmware": str(identity.get("firmware") or "brak odczytu"),
        "serial_number": str(identity.get("serial_number") or "brak odczytu"),
        "endpoint": endpoint_text,
        "unit_id": str(identity.get("unit_id") or "brak"),
        "serial_ports": "\n".join(port_lines) if port_lines else "brak wykrytych portów",
    }


class ThesslaGreenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one gateway without touching Modbus from Home Assistant."""

    VERSION = 1

    def __init__(self) -> None:
        self._pending_entry_data: dict[str, str] | None = None
        self._pending_title = "Thessla Green"
        self._pending_discovery: dict[str, str] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = str(user_input[CONF_URL]).strip().rstrip("/")
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors[CONF_URL] = "invalid_url"
            else:
                api = GatewayApi(
                    async_get_clientsession(self.hass),
                    url,
                    str(user_input.get(CONF_TOKEN, "")).strip() or None,
                )
                try:
                    state = await api.async_test_connection()
                except GatewayAuthError:
                    errors["base"] = "invalid_auth"
                except GatewayError:
                    errors["base"] = "cannot_connect"
                else:
                    identity = state.get("identity") if isinstance(state, dict) else None
                    identity = identity if isinstance(identity, dict) else {}
                    if not identity:
                        errors["base"] = "device_not_found"
                    else:
                        try:
                            serial_ports = await api.async_get_serial_ports()
                        except GatewayError:
                            # Older gateways may not expose the optional inventory route;
                            # a valid state response is still sufficient to configure HA.
                            serial_ports = {}
                        stable_id = str(identity.get("stable_id") or url)
                        await self.async_set_unique_id(stable_id)
                        self._abort_if_unique_id_configured()
                        self._pending_entry_data = {
                            CONF_URL: url,
                            CONF_TOKEN: str(user_input.get(CONF_TOKEN, "")).strip(),
                        }
                        self._pending_title = str(identity.get("model") or "Thessla Green Gateway")
                        self._pending_discovery = _format_discovery_details(state, serial_ports)
                        return await self.async_step_confirm()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=DEFAULT_URL): str,
                    vol.Optional(CONF_TOKEN, default=""): str,
                }
            ),
            errors=errors,
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the discovered AirPack and show the gateway's Modbus evidence."""

        if self._pending_entry_data is None:
            return self.async_abort(reason="unknown_error")
        if user_input is not None:
            data = self._pending_entry_data
            self._pending_entry_data = None
            return self.async_create_entry(title=self._pending_title, data=data)
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders=self._pending_discovery,
            last_step=True,
        )

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="unknown_error")
        errors: dict[str, str] = {}
        if user_input is not None:
            token = str(user_input.get(CONF_TOKEN, "")).strip() or None
            api = GatewayApi(
                async_get_clientsession(self.hass),
                entry.data[CONF_URL],
                token,
            )
            try:
                await api.async_test_connection()
            except GatewayAuthError:
                errors["base"] = "invalid_auth"
            except GatewayError:
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_TOKEN: token or ""},
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
        return self.async_show_form(
            step_id="reauth",
            data_schema=vol.Schema({vol.Optional(CONF_TOKEN, default=""): str}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the gateway URL or token without deleting the device."""

        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="unknown_error")

        errors: dict[str, str] = {}
        if user_input is not None:
            url = str(user_input[CONF_URL]).strip().rstrip("/")
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors[CONF_URL] = "invalid_url"
            else:
                token = str(user_input.get(CONF_TOKEN, "")).strip() or None
                api = GatewayApi(async_get_clientsession(self.hass), url, token)
                try:
                    await api.async_test_connection()
                except GatewayAuthError:
                    errors["base"] = "invalid_auth"
                except GatewayError:
                    errors["base"] = "cannot_connect"
                else:
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={CONF_URL: url, CONF_TOKEN: token or ""},
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=entry.data.get(CONF_URL, DEFAULT_URL)): str,
                    vol.Optional(CONF_TOKEN, default=entry.data.get(CONF_TOKEN, "")): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return ThesslaGreenOptionsFlow()


class ThesslaGreenOptionsFlow(config_entries.OptionsFlow):
    """Keep options flow intentionally small until gateway settings mature."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({}),
        )
