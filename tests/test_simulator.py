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
        assert state.identity.serial_number == "7edf c31b 0000"
        assert state.values["supply_percentage"] == 30
        assert state.values["extract_percentage"] == 30
        assert state.values["constant_flow_active"] is True
        assert state.values["supply_flowrate"] == 180
        assert state.values["extract_flowrate"] == 176
        assert state.values["fpx_system_active"] is True
        assert state.values["fpx_stage"] == 1
        assert state.values["erv_post_heater_active"] is True
        assert state.values["erv_post_heater_mode"] == 2
        initial_airflow = state.values["supply_airflow"]
        assert isinstance(initial_airflow, (int, float))

        await gateway.set_mode(1)
        await gateway.set_fan_speed(80)
        assert gateway.state.values["manual_fan_speed"] == 80
        assert gateway.state.values["supply_percentage"] == 80
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

        temporary = await gateway.execute_command(
            "activate_temporary_mode",
            {"percentage": 70},
            request_id="simulator-temporary-mode",
        )
        temporary_state = temporary["state"]
        assert isinstance(temporary_state, dict)
        temporary_values = temporary_state["values"]
        assert isinstance(temporary_values, dict)
        assert temporary_values["mode"] == 2
        assert temporary_values["temporary_fan_speed"] == 70
        assert transport.write_blocks[-1] == (4400, (2, 70, 1), 10)
        await gateway.stop()

    asyncio.run(run())


def test_simulator_maps_inactive_constant_flow_to_unavailable_measurements() -> None:
    async def run() -> None:
        transport = SimulatedAirPackTransport(constant_flow_active=False)
        gateway = GatewayService(transport, endpoint=transport.endpoint, unit_id=transport.unit_id)
        state = await gateway.start()

        assert state.values["constant_flow_available"] is False
        assert state.values["constant_flow_active"] is False
        assert state.values["supply_airflow"] is None
        assert state.values["extract_airflow"] is None
        assert state.values["supply_flowrate"] == 180
        assert state.values["extract_flowrate"] == 176

        response = await gateway.execute_command("set_fan_speed", {"percentage": 50})
        result = response["result"]
        assert isinstance(result, dict)
        observation = result["airflow_observation"]
        assert isinstance(observation, dict)
        assert observation["available"] is False
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
