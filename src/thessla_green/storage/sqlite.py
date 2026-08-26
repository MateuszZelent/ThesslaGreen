"""Small asynchronous SQLite store used by the local gateway.

The store opens short-lived SQLite connections and serializes its small,
bounded operations with an asyncio lock. It intentionally persists normalized
JSON contracts, so future storage backends can implement the same interface
without changing the protocol or adapters.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, TypeVar

from thessla_green.domain.models import AuditEvent, DeviceState

_T = TypeVar("_T")


def parse_sqlite_url(database_url: str) -> str:
    """Return a filesystem path from a supported ``sqlite:///`` URL."""

    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("only sqlite:/// database URLs are supported")
    path = database_url[len(prefix) :]
    if not path:
        raise ValueError("sqlite database path cannot be empty")
    return path


class EventStore(Protocol):
    """Persistence boundary consumed by the gateway application service."""

    async def initialize(self) -> None: ...

    async def record_state(self, state: DeviceState) -> None: ...

    async def record_audit(self, event: AuditEvent) -> None: ...

    async def list_states(
        self, *, limit: int = 100, since: str | None = None, until: str | None = None
    ) -> tuple[dict[str, object], ...]: ...

    async def list_audit(self, *, limit: int = 100) -> tuple[dict[str, object], ...]: ...

    async def get_command(self, request_id: str) -> dict[str, object] | None: ...

    async def record_command(
        self,
        request_id: str,
        fingerprint: str,
        response: Mapping[str, object],
        *,
        captured_at: str,
    ) -> None: ...


class SQLiteStore:
    """Bounded local event store for one gateway installation."""

    def __init__(
        self,
        database_url: str,
        *,
        max_state_rows: int = 10000,
        max_audit_rows: int = 5000,
        max_command_rows: int = 256,
    ) -> None:
        self.path = parse_sqlite_url(database_url)
        if max_state_rows < 1 or max_audit_rows < 1 or max_command_rows < 1:
            raise ValueError("SQLite retention limits must be positive")
        self.max_state_rows = max_state_rows
        self.max_audit_rows = max_audit_rows
        self.max_command_rows = max_command_rows
        self._lock = asyncio.Lock()
        self._memory_connection: sqlite3.Connection | None = None

    async def initialize(self) -> None:
        await self._run(self._initialize_sync)

    async def backup_to(self, destination: str | Path, *, overwrite: bool = False) -> None:
        """Create a consistent SQLite backup without involving the Modbus owner."""

        destination_path = str(destination)
        if destination_path.startswith("sqlite:///"):
            destination_path = parse_sqlite_url(destination_path)
        if not destination_path or destination_path == ":memory:":
            raise ValueError("backup destination must be a filesystem path")
        source_path = Path(self.path).expanduser() if self.path != ":memory:" else None
        target_path = Path(destination_path).expanduser()
        if source_path is not None and source_path.resolve() == target_path.resolve():
            raise ValueError("backup destination must differ from the source database")
        if target_path.exists() and not overwrite:
            raise FileExistsError(
                f"backup destination already exists: {target_path}; use --force to replace it"
            )

        def backup() -> None:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            source = self._connect()
            target = sqlite3.connect(str(target_path), timeout=5)
            try:
                source.backup(target)
            finally:
                target.close()
                if self.path != ":memory:":
                    source.close()

        await self._run(backup)

    async def record_state(self, state: DeviceState) -> None:
        payload = state.to_dict()

        def write() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO telemetry
                        (captured_at, revision, online, quality, error, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state.captured_at.isoformat(),
                        state.revision,
                        int(state.online),
                        state.quality,
                        state.error,
                        self._json(payload),
                    ),
                )
                connection.execute(
                    """
                    DELETE FROM telemetry
                    WHERE id NOT IN (
                        SELECT id FROM telemetry ORDER BY id DESC LIMIT ?
                    )
                    """,
                    (self.max_state_rows,),
                )

        await self._run(write)

    async def record_audit(self, event: AuditEvent) -> None:
        payload = event.to_dict()

        def write() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO audit
                        (captured_at, sequence, source, command, register, address,
                         requested_value, confirmed_value, success, unit_id, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.captured_at.isoformat(),
                        event.sequence,
                        event.source,
                        event.command,
                        event.register,
                        event.address,
                        event.requested_value,
                        event.confirmed_value,
                        int(event.success),
                        event.unit_id,
                        self._json(payload),
                    ),
                )
                connection.execute(
                    """
                    DELETE FROM audit
                    WHERE id NOT IN (
                        SELECT id FROM audit ORDER BY id DESC LIMIT ?
                    )
                    """,
                    (self.max_audit_rows,),
                )

        await self._run(write)

    async def list_states(
        self, *, limit: int = 100, since: str | None = None, until: str | None = None
    ) -> tuple[dict[str, object], ...]:
        self._validate_limit(limit)

        def read() -> tuple[dict[str, object], ...]:
            clauses: list[str] = []
            values: list[object] = []
            if since is not None:
                clauses.append("captured_at >= ?")
                values.append(since)
            if until is not None:
                clauses.append("captured_at <= ?")
                values.append(until)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT payload_json FROM telemetry
                    {where}
                    ORDER BY id DESC LIMIT ?
                    """,
                    (*values, limit),
                ).fetchall()
            return tuple(self._decode(row[0]) for row in reversed(rows))

        return await self._run(read)

    async def list_audit(self, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        self._validate_limit(limit)

        def read() -> tuple[dict[str, object], ...]:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT payload_json FROM audit ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return tuple(self._decode(row[0]) for row in reversed(rows))

        return await self._run(read)

    async def get_command(self, request_id: str) -> dict[str, object] | None:
        if not request_id:
            raise ValueError("request_id cannot be empty")

        def read() -> dict[str, object] | None:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT fingerprint, captured_at, response_json
                    FROM command_cache WHERE request_id = ?
                    """,
                    (request_id,),
                ).fetchone()
            if row is None:
                return None
            response = self._decode(row[2])
            return {
                "fingerprint": str(row[0]),
                "captured_at": str(row[1]),
                "response": response,
            }

        return await self._run(read)

    async def record_command(
        self,
        request_id: str,
        fingerprint: str,
        response: Mapping[str, object],
        *,
        captured_at: str,
    ) -> None:
        if not request_id or not fingerprint or not captured_at:
            raise ValueError("request cache fields cannot be empty")
        response_json = self._json(response)

        def write() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO command_cache
                        (request_id, fingerprint, captured_at, response_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(request_id) DO UPDATE SET
                        fingerprint = excluded.fingerprint,
                        captured_at = excluded.captured_at,
                        response_json = excluded.response_json
                    """,
                    (request_id, fingerprint, captured_at, response_json),
                )
                connection.execute(
                    """
                    DELETE FROM command_cache
                    WHERE request_id NOT IN (
                        SELECT request_id FROM command_cache
                        ORDER BY rowid DESC LIMIT ?
                    )
                    """,
                    (self.max_command_rows,),
                )

        await self._run(write)

    async def _run(self, operation: Callable[[], _T]) -> _T:
        async with self._lock:
            # Queries are bounded by the retention limits and execute in a
            # single local SQLite transaction. Keeping them in this task
            # avoids executor/thread-affinity issues in embedded Python builds.
            return operation()

    def _connect(self) -> sqlite3.Connection:
        if self.path == ":memory:":
            if self._memory_connection is None:
                self._memory_connection = sqlite3.connect(":memory:")
                self._memory_connection.row_factory = sqlite3.Row
            return self._memory_connection
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_sync(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    online INTEGER NOT NULL,
                    quality TEXT NOT NULL,
                    error TEXT,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS telemetry_captured_at ON telemetry(captured_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    command TEXT NOT NULL,
                    register TEXT NOT NULL,
                    address INTEGER NOT NULL,
                    requested_value INTEGER NOT NULL,
                    confirmed_value INTEGER,
                    success INTEGER NOT NULL,
                    unit_id INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS audit_captured_at ON audit(captured_at)")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS command_cache (
                    request_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    response_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS command_cache_captured_at "
                "ON command_cache(captured_at)"
            )

    @staticmethod
    def _json(payload: Mapping[str, object]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _decode(value: object) -> dict[str, object]:
        if not isinstance(value, str):
            raise ValueError("stored SQLite payload is not text")
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise ValueError("stored SQLite payload is not an object")
        return {str(key): item for key, item in decoded.items()}

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
