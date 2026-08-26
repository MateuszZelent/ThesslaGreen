from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from thessla_green.application.control import CommandConflict
from thessla_green.application.gateway import GatewayNotStarted, GatewayService
from thessla_green.control import ControlIntent, IntentPriority, PolicyArbiter
from thessla_green.domain.models import TransportEndpoint, TransportKind
from thessla_green.protocol.transport import ReadResponseError
from thessla_green.storage import SQLiteStore


class FakeGatewayTransport:
    def __init__(self, endpoint: TransportEndpoint) -> None:
        self.endpoint = endpoint
        self.registers = {
            4192: 1,
            4198: 2,
            4208: 0,
            4209: 0,
            4210: 30,
            4211: 40,
            4224: 0,
            4304: 0,
            4305: 0,
            4320: 0,
            4330: 0,
            4387: 1,
            4704: 1,
            4711: 2,
        }
        self.writes: list[tuple[int, int]] = []
        self.write_blocks: list[tuple[int, tuple[int, ...]]] = []

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def read_input_registers(self, address: int, count: int, unit_id: int) -> tuple[int, ...]:
        if (address, count) == (0, 5):
            return (4, 84, 0, 0, 2)
        if (address, count) == (16, 7):
            return (215, 220, 225, 230, 235, 240, 245)
        if (address, count) == (24, 6):
            return (1, 2, 3, 4, 5, 6)
        if (address, count) == (256, 2):
            return (250, 245)
        if (address, count) == (271, 5):
            return (1, 30, 30, 330, 325)
        raise AssertionError((address, count, unit_id))

    async def read_holding_registers(
        self, address: int, count: int, unit_id: int
    ) -> tuple[int, ...]:
        return tuple(self.registers[address + offset] for offset in range(count))

    async def read_coils(self, address: int, count: int, unit_id: int) -> tuple[bool, ...]:
        return tuple(False for _ in range(count))

    async def read_discrete_inputs(
        self, address: int, count: int, unit_id: int
    ) -> tuple[bool, ...]:
        return tuple(False for _ in range(count))

    async def write_holding_register(self, address: int, value: int, unit_id: int) -> None:
        self.writes.append((address, value))
        self.registers[address] = value

    async def write_holding_registers(
        self, address: int, values: Sequence[int], unit_id: int
    ) -> None:
        normalized = tuple(values)
        self.write_blocks.append((address, normalized))
        if address == 4400 and len(normalized) == 3 and normalized[2] == 1:
            self.registers[4208] = normalized[0]
            self.registers[4211] = normalized[1]


def test_gateway_confirms_identity_before_control(tmp_path: Path) -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        transport = FakeGatewayTransport(endpoint)
        gateway = GatewayService(
            transport,
            endpoint=endpoint,
            unit_id=10,
            store=SQLiteStore(f"sqlite:///{tmp_path / 'gateway.db'}"),
        )

        state = await gateway.start()
        assert state.online
        assert state.identity is not None
        assert state.identity.firmware == (4, 84, 2)
        assert state.values["constant_flow_active"] is True
        assert state.values["supply_flowrate"] == 330
        assert state.values["extract_flowrate"] == 325
        assert state.values["fpx_system_active"] is True
        assert state.values["fpx_stage"] == 2
        assert state.values["erv_post_heater_active"] is True
        assert state.values["erv_post_heater_mode"] == 2

        result = await gateway.set_fan_speed(60)
        assert result.confirmed
        assert transport.writes == [(4210, 60)]
        assert len(await gateway.telemetry()) >= 2
        stored_audit = await gateway.stored_audit()
        assert stored_audit[-1]["confirmed_value"] == 60
        await gateway.stop()

    asyncio.run(run())


def test_gateway_keeps_older_firmware_online_when_heater_diagnostics_are_unsupported() -> None:
    class OlderFirmwareTransport(FakeGatewayTransport):
        async def read_holding_registers(
            self, address: int, count: int, unit_id: int
        ) -> tuple[int, ...]:
            if address in {4704, 4711}:
                raise ReadResponseError("illegal data address")
            return await super().read_holding_registers(address, count, unit_id)

    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        gateway = GatewayService(
            OlderFirmwareTransport(endpoint), endpoint=endpoint, unit_id=10
        )

        state = await gateway.start()

        assert state.online
        assert state.values["erv_post_heater_active"] is None
        assert state.values["erv_post_heater_mode"] is None
        await gateway.stop()

    asyncio.run(run())


def test_gateway_atomically_activates_temporary_mode() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        transport = FakeGatewayTransport(endpoint)
        gateway = GatewayService(transport, endpoint=endpoint, unit_id=10)
        await gateway.start()

        response = await gateway.execute_command(
            "activate_temporary_mode",
            {"percentage": 65},
            request_id="temporary-mode-1",
        )

        assert response["status"] == "confirmed"
        assert gateway.state.values["mode"] == 2
        assert gateway.state.values["temporary_fan_speed"] == 65
        assert transport.write_blocks == [(4400, (2, 65, 1))]
        assert transport.writes == []
        await gateway.stop()

    asyncio.run(run())


def test_gateway_sets_and_confirms_comfort_preference() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        transport = FakeGatewayTransport(endpoint)
        gateway = GatewayService(transport, endpoint=endpoint, unit_id=10)
        await gateway.start()

        response = await gateway.execute_command(
            "set_comfort_mode", {"mode": "comfort"}, request_id="comfort-1"
        )

        assert response["status"] == "confirmed"
        assert gateway.state.values["comfort_mode_panel"] == 1
        assert transport.writes == [(4304, 1)]
        await gateway.stop()

    asyncio.run(run())


def test_gateway_rejects_observable_input_driven_special_mode_commands() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        transport = FakeGatewayTransport(endpoint)
        gateway = GatewayService(transport, endpoint=endpoint, unit_id=10)
        await gateway.start()

        with pytest.raises(ValueError, match="not safe"):
            await gateway.execute_command("set_special_mode", {"mode": "airing_button"})
        with pytest.raises(ValueError, match="not safe"):
            await gateway.execute_command("set_special_mode", {"mode": 3})
        assert transport.writes == []
        await gateway.stop()

    asyncio.run(run())


def test_gateway_polling_refreshes_state_and_stops_cleanly() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        gateway = GatewayService(
            FakeGatewayTransport(endpoint), endpoint=endpoint, unit_id=10
        )

        await gateway.start()
        initial_revision = gateway.state.revision
        gateway.start_polling(0.001)
        await asyncio.sleep(0.01)

        assert gateway.state.revision > initial_revision
        await gateway.stop()
        assert gateway._poll_task is None

    asyncio.run(run())


def test_gateway_lease_rejects_a_second_local_owner() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyLEASE")
        first = GatewayService(FakeGatewayTransport(endpoint), endpoint=endpoint, unit_id=10)
        second = GatewayService(FakeGatewayTransport(endpoint), endpoint=endpoint, unit_id=10)

        await first.start()
        with pytest.raises(GatewayNotStarted, match="already owned"):
            await second.start()

        await first.stop()
        await second.start()
        await second.stop()

    asyncio.run(run())


def test_gateway_replays_same_request_id_without_a_second_write() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        transport = FakeGatewayTransport(endpoint)
        gateway = GatewayService(transport, endpoint=endpoint, unit_id=10)

        await gateway.start()
        first = await gateway.execute_command(
            "set_fan_speed",
            {"percentage": 60},
            request_id="mobile-1",
            source="mobile",
        )
        replay = await gateway.execute_command(
            "set_fan_speed",
            {"percentage": 60},
            request_id="mobile-1",
            source="mobile",
        )

        assert first["replayed"] is False
        assert replay["replayed"] is True
        assert replay["result"] == first["result"]
        result = first["result"]
        assert isinstance(result, dict)
        observation = result["airflow_observation"]
        assert isinstance(observation, dict)
        assert observation["available"] is True
        assert observation["supply_changed"] is False
        assert transport.writes == [(4210, 60)]
        await gateway.stop()

    asyncio.run(run())


def test_gateway_can_sample_delayed_airflow_window(tmp_path: Path) -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        gateway = GatewayService(
            FakeGatewayTransport(endpoint),
            endpoint=endpoint,
            unit_id=10,
            store=SQLiteStore(f"sqlite:///{tmp_path / 'airflow-window.db'}"),
            airflow_observation_seconds=0.004,
            airflow_observation_interval_seconds=0.001,
        )

        await gateway.start()
        response = await gateway.execute_command(
            "set_fan_speed",
            {"percentage": 60},
            request_id="airflow-window-1",
        )
        result = response["result"]
        assert isinstance(result, dict)
        observation = result["airflow_observation"]
        assert isinstance(observation, dict)
        assert observation["changed_within_window"] is False
        samples = observation["samples"]
        assert isinstance(samples, list)
        assert len(samples) >= 2
        await gateway.stop()

    asyncio.run(run())


def test_gateway_rejects_reused_request_id_and_stale_revision() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        transport = FakeGatewayTransport(endpoint)
        gateway = GatewayService(transport, endpoint=endpoint, unit_id=10)

        await gateway.start()
        expected_revision = gateway.state.revision
        await gateway.execute_command(
            "set_fan_speed", {"percentage": 60}, request_id="mobile-2"
        )

        with pytest.raises(CommandConflict, match="different command"):
            await gateway.execute_command(
                "set_fan_speed", {"percentage": 70}, request_id="mobile-2"
            )
        with pytest.raises(CommandConflict, match="expected state revision"):
            await gateway.execute_command(
                "set_mode",
                {"mode": "manual"},
                expected_revision=expected_revision,
            )
        await gateway.stop()

    asyncio.run(run())


def test_gateway_replays_a_persisted_request_after_restart(tmp_path: Path) -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        transport = FakeGatewayTransport(endpoint)
        database_url = f"sqlite:///{tmp_path / 'idempotency.db'}"

        first_gateway = GatewayService(
            transport,
            endpoint=endpoint,
            unit_id=10,
            store=SQLiteStore(database_url),
        )
        await first_gateway.start()
        first = await first_gateway.execute_command(
            "set_fan_speed",
            {"percentage": 60},
            request_id="restart-safe-1",
            source="mobile",
        )
        await first_gateway.stop()

        restarted_gateway = GatewayService(
            transport,
            endpoint=endpoint,
            unit_id=10,
            store=SQLiteStore(database_url),
        )
        await restarted_gateway.start()
        replay = await restarted_gateway.execute_command(
            "set_fan_speed",
            {"percentage": 60},
            request_id="restart-safe-1",
            source="mobile",
        )

        assert first["replayed"] is False
        assert replay["replayed"] is True
        assert replay["result"] == first["result"]
        assert transport.writes == [(4210, 60)]
        await restarted_gateway.stop()

    asyncio.run(run())


def test_gateway_expires_old_persisted_request_cache(tmp_path: Path) -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        database_url = f"sqlite:///{tmp_path / 'expired-idempotency.db'}"
        store = SQLiteStore(database_url)
        await store.initialize()
        await store.record_command(
            "expired-1",
            gateway_fingerprint("set_fan_speed", {"percentage": 60}),
            {"status": "confirmed", "request_id": "expired-1"},
            captured_at="2020-01-01T00:00:00+00:00",
        )
        transport = FakeGatewayTransport(endpoint)
        gateway = GatewayService(
            transport,
            endpoint=endpoint,
            unit_id=10,
            store=store,
            command_cache_ttl_seconds=60,
        )
        await gateway.start()
        result = await gateway.execute_command(
            "set_fan_speed",
            {"percentage": 60},
            request_id="expired-1",
        )

        assert result["replayed"] is False
        assert transport.writes == [(4210, 60)]
        await gateway.stop()

    asyncio.run(run())


def test_gateway_executes_only_selected_policy_intent() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        transport = FakeGatewayTransport(endpoint)
        gateway = GatewayService(transport, endpoint=endpoint, unit_id=10)
        await gateway.start()

        now = datetime.now(UTC)
        arbiter = PolicyArbiter()
        decision = arbiter.decide(
            [
                ControlIntent(
                    command_type="set_fan_speed",
                    parameters={"percentage": 60},
                    priority=IntentPriority.MANUAL,
                    source="automation",
                    reason="manual test intent",
                    created_at=now,
                )
            ],
            at=now,
        )
        response = await gateway.execute_policy_decision(decision)

        result = response["result"]
        assert isinstance(result, dict)
        assert result["confirmed"] is True
        assert transport.writes == [(4210, 60)]
        await gateway.stop()

    asyncio.run(run())


def gateway_fingerprint(command_type: str, parameters: dict[str, object]) -> str:
    """Keep the fixture fingerprint aligned with the gateway's public behavior."""

    import hashlib
    import json

    encoded = json.dumps(
        {"type": command_type, "parameters": parameters},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
