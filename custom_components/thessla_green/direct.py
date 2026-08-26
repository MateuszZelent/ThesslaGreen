"""Direct Home Assistant runtime owning one Thessla Green Modbus endpoint."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from ._core.application.control import (
    USER_SELECTABLE_SPECIAL_MODES,
    AirPackMode,
    ComfortPreference,
)
from ._core.application.gateway import GatewayService
from ._core.domain.models import TransportEndpoint
from ._core.protocol.transport import PymodbusTransport


class DirectModbusApi:
    """Expose the same typed client boundary as the external HTTP gateway."""

    def __init__(self, endpoint: TransportEndpoint, unit_id: int) -> None:
        self.endpoint = endpoint
        self.unit_id = unit_id
        self.service = GatewayService(
            PymodbusTransport(endpoint),
            endpoint=endpoint,
            unit_id=unit_id,
            airflow_observation_seconds=0.0,
        )

    async def async_start(self) -> dict[str, Any]:
        return (await self.service.start()).to_dict()

    async def async_close(self) -> None:
        await self.service.stop()

    async def async_test_connection(self) -> dict[str, Any]:
        if self.service.state.identity is None:
            return await self.async_start()
        return self.service.state.to_dict()

    async def async_get_state(self) -> dict[str, Any]:
        return (await self.service.refresh()).to_dict()

    async def async_get_capabilities(self) -> dict[str, Any]:
        return self.service.state.capabilities.to_dict()

    async def async_get_control_options(self) -> dict[str, Any]:
        return {
            "fan_speed": {"minimum": 10, "maximum": 100, "unit": "%"},
            "temporary_fan_speed": {"minimum": 10, "maximum": 100, "unit": "%"},
            "temporary_mode": {
                "duration_source": "airpack_controller_settings",
                "duration_writable": False,
                "activation": "atomic_register_block_4400_4402",
            },
            "modes": {mode.name.lower(): int(mode) for mode in AirPackMode},
            "comfort_modes": {mode.name.lower(): int(mode) for mode in ComfortPreference},
            "special_modes": {
                name: int(mode) for mode, name in USER_SELECTABLE_SPECIAL_MODES.items()
            },
        }

    async def async_get_serial_ports(self) -> dict[str, Any]:
        from ._core.discovery.candidates import enumerate_serial_ports

        ports = await asyncio.to_thread(enumerate_serial_ports)
        return {"ports": [port.to_dict() for port in ports]}

    async def async_command(
        self,
        command_type: str,
        parameters: Mapping[str, object],
        *,
        request_id: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        response = await self.service.execute_command(
            command_type,
            parameters,
            source="home_assistant",
            request_id=request_id or str(uuid4()),
            expected_revision=expected_revision,
        )
        return dict(response)
