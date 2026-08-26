"""UI setup for a selected local FastAPI gateway."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GatewayApi, GatewayAuthError, GatewayError
from .const import CONF_TOKEN, CONF_URL, DEFAULT_URL, DOMAIN


class ThesslaGreenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one gateway without touching Modbus from Home Assistant."""

    VERSION = 1

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
                    stable_id = str(identity.get("stable_id") or url)
                    await self.async_set_unique_id(stable_id)
                    self._abort_if_unique_id_configured()
                    title = str(identity.get("model") or "Thessla Green Gateway")
                    return self.async_create_entry(
                        title=title,
                        data={
                            CONF_URL: url,
                            CONF_TOKEN: str(user_input.get(CONF_TOKEN, "")).strip(),
                        },
                    )

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
