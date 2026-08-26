from __future__ import annotations

import asyncio

import pytest

from thessla_green.application.control import ControlVerificationError
from thessla_green.application.gateway import GatewayService
from thessla_green.protocol.simulator import SimulatedAirPackTransport


def test_simulator_supports_discovery_control_and_airflow_feedback() -> None:
    async def run() -> None:
        transport = SimulatedAirPackTransport()
        gateway = GatewayService(
            transport,
            endpoint=transport.endpoint,
            unit_id=transport.unit_id,
        )

        state = await gateway.start()
        assert state.online
        assert state.identity is not None
        assert state.identity.firmware == (4, 85, 16)
        initial_airflow = state.values["supply_airflow"]
        assert isinstance(initial_airflow, (int, float))

        await gateway.set_mode(1)
        await gateway.set_fan_speed(80)
        assert gateway.state.values["manual_fan_speed"] == 80
        airflow = gateway.state.values["supply_airflow"]
        assert isinstance(airflow, (int, float))
        assert airflow > initial_airflow
        assert transport.writes[-1] == (4210, 80, 10)

        response = await gateway.execute_command(
            "set_fan_speed",
            {"percentage": 40},
            request_id="simulator-airflow-observation",
        )
        result = response["result"]
        assert isinstance(result, dict)
        observation = result["airflow_observation"]
        assert isinstance(observation, dict)
        assert observation["available"] is True
        assert observation["supply_changed"] is True
        await gateway.stop()

    asyncio.run(run())


def test_simulator_reports_windowed_airflow_observation() -> None:
    async def run() -> None:
        transport = SimulatedAirPackTransport()
        gateway = GatewayService(
            transport,
            endpoint=transport.endpoint,
            unit_id=transport.unit_id,
            airflow_observation_seconds=0.01,
            airflow_observation_interval_seconds=0.001,
        )
        await gateway.start()

        response = await gateway.execute_command(
            "set_fan_speed",
            {"percentage": 80},
            request_id="simulator-windowed-observation",
        )
        result = response["result"]
        assert isinstance(result, dict)
        observation = result["airflow_observation"]
        assert isinstance(observation, dict)
        assert observation["changed_within_window"] is True
        assert observation["observation_window_seconds"] >= 0
        await gateway.stop()

    asyncio.run(run())


def test_simulator_can_model_a_readback_fault() -> None:
    async def run() -> None:
        transport = SimulatedAirPackTransport(readback_offset=1)
        gateway = GatewayService(transport, endpoint=transport.endpoint, unit_id=transport.unit_id)
        await gateway.start()

        with pytest.raises(ControlVerificationError, match="read-back"):
            await gateway.set_fan_speed(60)
        assert gateway.audit_events[-1].success is False
        await gateway.stop()

    asyncio.run(run())
