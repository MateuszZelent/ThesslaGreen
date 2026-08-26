"""Framework-independent local persistence for gateway snapshots and audit."""

from .sqlite import EventStore, SQLiteStore, parse_sqlite_url

__all__ = ["EventStore", "SQLiteStore", "parse_sqlite_url"]
