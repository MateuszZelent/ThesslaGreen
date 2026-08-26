from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from thessla_green.domain.models import (
    AuditEvent,
    Capabilities,
    DeviceIdentity,
    DeviceState,
    TransportEndpoint,
    TransportKind,
)
from thessla_green.storage import SQLiteStore, parse_sqlite_url


def test_parse_sqlite_url_rejects_non_local_backends() -> None:
    assert parse_sqlite_url("sqlite:///./events.db") == "./events.db"
    with pytest.raises(ValueError, match="only sqlite"):
        parse_sqlite_url("postgresql://localhost/events")


def test_sqlite_store_round_trips_state_and_audit(tmp_path: Path) -> None:
    async def run() -> None:
        database = tmp_path / "events.db"
        store = SQLiteStore(f"sqlite:///{database}", max_state_rows=2, max_audit_rows=2)
        await store.initialize()

        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        identity = DeviceIdentity(
            model="AirPack4",
            unit_id=10,
            firmware=(4, 85, 16),
            serial_number="007e 00df",
            endpoint=endpoint,
        )
        state = DeviceState(
            revision=3,
            captured_at=datetime.now(UTC),
            online=True,
            identity=identity,
            capabilities=Capabilities(features=frozenset({"airflow"})),
            values={"manual_fan_speed": 40, "supply_airflow": 500},
            quality="complete",
        )
        await store.record_state(state)
        event = AuditEvent(
            sequence=1,
            captured_at=datetime.now(UTC),
            source="test",
            command="set_fan_speed",
            register="manual_fan_speed",
            address=4210,
            requested_value=40,
            confirmed_value=40,
            success=True,
            endpoint=endpoint,
            unit_id=10,
        )
        await store.record_audit(event)

        states = await store.list_states()
        audits = await store.list_audit()
        assert states[0]["revision"] == 3
        assert states[0]["values"] == {"manual_fan_speed": 40, "supply_airflow": 500}
        assert audits[0]["confirmed_value"] == 40
        assert audits[0]["success"] is True

    asyncio.run(run())


def test_sqlite_store_applies_retention_limits(tmp_path: Path) -> None:
    async def run() -> None:
        store = SQLiteStore(f"sqlite:///{tmp_path / 'retention.db'}", max_state_rows=1)
        await store.initialize()
        for revision in (1, 2):
            await store.record_state(DeviceState(revision=revision))
        states = await store.list_states()
        assert [state["revision"] for state in states] == [2]

    asyncio.run(run())


def test_sqlite_memory_store_keeps_one_connection_for_lifetime() -> None:
    async def run() -> None:
        store = SQLiteStore("sqlite:///:memory:")
        await store.initialize()
        await store.record_state(DeviceState(revision=1, online=True, quality="complete"))
        points = await store.list_states()
        assert [point["revision"] for point in points] == [1]

    asyncio.run(run())


def test_sqlite_store_round_trips_command_cache_and_applies_retention(tmp_path: Path) -> None:
    async def run() -> None:
        store = SQLiteStore(
            f"sqlite:///{tmp_path / 'commands.db'}",
            max_command_rows=1,
        )
        await store.initialize()
        await store.record_command(
            "old",
            "fingerprint-old",
            {"status": "confirmed", "request_id": "old"},
            captured_at="2026-01-01T00:00:00+00:00",
        )
        await store.record_command(
            "new",
            "fingerprint-new",
            {"status": "confirmed", "request_id": "new"},
            captured_at="2026-01-02T00:00:00+00:00",
        )

        assert await store.get_command("old") is None
        cached = await store.get_command("new")
        assert cached is not None
        assert cached["fingerprint"] == "fingerprint-new"
        assert cached["response"] == {"status": "confirmed", "request_id": "new"}

    asyncio.run(run())


def test_sqlite_store_creates_consistent_backup_and_protects_destination(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        source_path = tmp_path / "source.db"
        destination_path = tmp_path / "backup.db"
        source = SQLiteStore(f"sqlite:///{source_path}")
        await source.initialize()
        await source.record_state(DeviceState(revision=7, online=True, quality="complete"))

        await source.backup_to(destination_path)
        backup = SQLiteStore(f"sqlite:///{destination_path}")
        await backup.initialize()
        points = await backup.list_states()
        assert [point["revision"] for point in points] == [7]

        with pytest.raises(FileExistsError, match="already exists"):
            await source.backup_to(destination_path)
        await source.backup_to(destination_path, overwrite=True)

    asyncio.run(run())
