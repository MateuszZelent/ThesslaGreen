"""Async HTTP client for the local FastAPI gateway."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from aiohttp import ClientError, ClientResponseError, ClientSession


class GatewayError(RuntimeError):
    """Base error returned by the gateway adapter."""


class GatewayAuthError(GatewayError):
    """The gateway rejected the configured token."""


class GatewayUnavailable(GatewayError):
    """The gateway could not be reached or returned an invalid response."""


class GatewayApi:
    """Thin client; state and control policy remain in the gateway."""

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        token: str | None = None,
    ) -> None:
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.token = token or None

    async def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if extra_headers:
            headers.update(extra_headers)
        try:
            async with self.session.request(
                method,
                f"{self.base_url}{path}",
                json=payload,
                headers=headers,
            ) as response:
                if response.status in (401, 403):
                    raise GatewayAuthError("gateway rejected the configured token")
                response.raise_for_status()
                body = await response.json()
                if not isinstance(body, dict):
                    raise GatewayUnavailable("gateway returned a non-object JSON response")
                return body
        except GatewayError:
            raise
        except (ClientError, ClientResponseError, TimeoutError, ValueError) as exc:
            raise GatewayUnavailable(str(exc)) from exc

    async def async_test_connection(self) -> dict[str, Any]:
        """Verify liveness and that a selected AirPack state is available."""

        await self._request("GET", "/health/live")
        return await self._request("GET", "/api/v1/state")

    async def async_get_state(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/state")

    async def async_get_devices(self) -> dict[str, Any]:
        """Return the gateway's discovered devices without probing Modbus."""

        return await self._request("GET", "/api/v1/devices")

    async def async_get_serial_ports(self) -> dict[str, Any]:
        """Return read-only serial candidates reported by the gateway host."""

        return await self._request("GET", "/api/v1/discovery/serial-ports")

    async def async_get_capabilities(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/capabilities")

    async def async_get_control_options(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/control/options")

    async def async_command(
        self,
        command_type: str,
        parameters: Mapping[str, object],
        *,
        request_id: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Send a typed command with a stable ID for the HTTP request."""

        payload: dict[str, object] = {
            "type": command_type,
            "parameters": dict(parameters),
            "request_id": request_id or str(uuid4()),
        }
        if expected_revision is not None:
            payload["expected_revision"] = expected_revision
        return await self._request(
            "POST",
            "/api/v1/commands",
            payload,
            {"X-Thessla-Source": "home_assistant"},
        )
