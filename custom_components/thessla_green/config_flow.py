"""UI setup for direct Modbus and optional external-gateway deployments."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ._core.discovery.candidates import SerialPortInfo, enumerate_serial_ports
from ._core.discovery.probe import AirPackProbe
from ._core.domain.models import DiscoveryResult, TransportEndpoint, TransportKind
from ._core.protocol.transport import (
    ModbusTransportError,
    PymodbusTransport,
    PymodbusUnavailable,
    SerialPortBusy,
)
from .api import GatewayApi, GatewayAuthError, GatewayError
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
    DEFAULT_URL,
    DOMAIN,
)


def _identity_details(state: Mapping[str, Any]) -> dict[str, str]:
    identity = state.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    endpoint = identity.get("endpoint")
    endpoint = endpoint if isinstance(endpoint, Mapping) else {}
    return {
        "model": str(identity.get("model") or "AirPack"),
        "firmware": str(identity.get("firmware") or "brak odczytu"),
        "serial_number": str(identity.get("serial_number") or "brak odczytu"),
        "endpoint": str(endpoint.get("key") or endpoint.get("address") or "brak"),
        "unit_id": str(identity.get("unit_id") or "brak"),
    }


def _port_description(ports: tuple[SerialPortInfo, ...]) -> str:
    if not ports:
        return "Nie wykryto portów. Sprawdź mapowanie USB i uprawnienia Home Assistanta."
    return "\n".join(
        f"{port.device}" + (f" — {port.description}" if port.description else "") for port in ports
    )


async def _probe_serial(
    serial_port: str,
    unit_id: int,
    baudrate: int,
    timeout: float,
) -> DiscoveryResult:
    endpoint = TransportEndpoint(
        TransportKind.SERIAL,
        serial_port,
        baudrate=baudrate,
        timeout_seconds=timeout,
    )
    transport = PymodbusTransport(endpoint)
    try:
        await transport.connect()
        return await AirPackProbe().run(transport, endpoint, unit_id)
    finally:
        await transport.close()


class ThesslaGreenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one AirPack with exactly one selected Modbus owner."""

    VERSION = 2

    def __init__(self) -> None:
        self._pending_entry_data: dict[str, Any] | None = None
        self._pending_title = "Thessla Green"
        self._pending_discovery: dict[str, str] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options=[CONNECTION_DIRECT, CONNECTION_GATEWAY],
        )

    async def async_step_direct(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Discover and verify a serial AirPack directly from Home Assistant."""

        ports = await self.hass.async_add_executor_job(enumerate_serial_ports)
        errors: dict[str, str] = {}
        if user_input is not None:
            serial_port = str(user_input[CONF_SERIAL_PORT]).strip()
            unit_id = int(user_input[CONF_UNIT_ID])
            baudrate = int(user_input[CONF_BAUDRATE])
            timeout = float(user_input[CONF_TIMEOUT])
            try:
                result = await _probe_serial(serial_port, unit_id, baudrate, timeout)
            except SerialPortBusy:
                errors["base"] = "port_busy"
            except PermissionError:
                errors["base"] = "permission_denied"
            except FileNotFoundError:
                errors["base"] = "serial_not_found"
            except PymodbusUnavailable:
                errors["base"] = "missing_dependency"
            except (ModbusTransportError, OSError, TimeoutError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                if not result.is_selectable or result.identity is None:
                    errors["base"] = "device_not_found"
                else:
                    await self.async_set_unique_id(result.identity.stable_id)
                    self._abort_if_unique_id_configured()
                    self._pending_entry_data = {
                        CONF_CONNECTION_TYPE: CONNECTION_DIRECT,
                        CONF_SERIAL_PORT: serial_port,
                        CONF_UNIT_ID: unit_id,
                        CONF_BAUDRATE: baudrate,
                        CONF_TIMEOUT: timeout,
                    }
                    self._pending_title = result.identity.model
                    self._pending_discovery = {
                        **_identity_details({"identity": result.identity.to_dict()}),
                        "connection": (
                            "Bezpośredni Modbus RTU — Home Assistant jest właścicielem portu"
                        ),
                    }
                    return await self.async_step_confirm()

        default_port = ports[0].device if ports else "/dev/serial/by-id/"
        return self.async_show_form(
            step_id="direct",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERIAL_PORT, default=default_port): str,
                    vol.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=247)
                    ),
                    vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): vol.In(
                        [9600, 19200, 38400, 57600, 115200]
                    ),
                    vol.Required(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): vol.All(
                        vol.Coerce(float), vol.Range(min=0.2, max=10.0)
                    ),
                }
            ),
            description_placeholders={"serial_ports": _port_description(ports)},
            errors=errors,
        )

    async def async_step_gateway(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the optional external FastAPI owner."""

        errors: dict[str, str] = {}
        if user_input is not None:
            url = str(user_input[CONF_URL]).strip().rstrip("/")
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors[CONF_URL] = "invalid_url"
            else:
                token = str(user_input.get(CONF_TOKEN, "")).strip()
                api = GatewayApi(async_get_clientsession(self.hass), url, token or None)
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
                        stable_id = str(identity.get("stable_id") or url)
                        await self.async_set_unique_id(stable_id)
                        self._abort_if_unique_id_configured()
                        self._pending_entry_data = {
                            CONF_CONNECTION_TYPE: CONNECTION_GATEWAY,
                            CONF_URL: url,
                            CONF_TOKEN: token,
                        }
                        self._pending_title = str(identity.get("model") or "Thessla Green")
                        self._pending_discovery = {
                            **_identity_details(state),
                            "connection": "Zewnętrzny gateway FastAPI jest właścicielem Modbus",
                        }
                        return await self.async_step_confirm()

        return self.async_show_form(
            step_id="gateway",
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
        if entry is None or entry.data.get(CONF_CONNECTION_TYPE) == CONNECTION_DIRECT:
            return self.async_abort(reason="unknown_error")
        errors: dict[str, str] = {}
        if user_input is not None:
            token = str(user_input.get(CONF_TOKEN, "")).strip() or None
            api = GatewayApi(async_get_clientsession(self.hass), entry.data[CONF_URL], token)
            try:
                await api.async_test_connection()
            except GatewayAuthError:
                errors["base"] = "invalid_auth"
            except GatewayError:
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_TOKEN: token or ""}
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
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="unknown_error")
        if entry.data.get(CONF_CONNECTION_TYPE) == CONNECTION_DIRECT:
            return self.async_abort(reason="reconfigure_via_readd")
        return await self._async_reconfigure_gateway(entry, user_input)

    async def _async_reconfigure_gateway(
        self,
        entry: config_entries.ConfigEntry,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
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
                        data={
                            CONF_CONNECTION_TYPE: CONNECTION_GATEWAY,
                            CONF_URL: url,
                            CONF_TOKEN: token or "",
                        },
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
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(step_id="init", data_schema=vol.Schema({}))
