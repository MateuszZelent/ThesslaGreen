"""Environment-backed configuration without a framework dependency."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from thessla_green.domain.models import TransportEndpoint, TransportKind


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _ints(value: str | None, *, name: str) -> tuple[int, ...]:
    values = _csv(value)
    try:
        return tuple(int(item, 0) for item in values)
    except ValueError as exc:
        raise ValueError(f"{name} must contain comma-separated integers") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings for the gateway and bounded discovery.

    Network scanning is opt-in: empty ``discovery_cidrs`` means that only
    configured TCP hosts and local serial ports are considered.
    """

    transport: TransportKind = TransportKind.SERIAL
    serial_port: str | None = None
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: int = 1
    host: str | None = None
    modbus_port: int = 502
    gateway_port: int = 8899
    device_id: int = 10
    discovery_device_ids: tuple[int, ...] = (10,)
    discovery_bauds: tuple[int, ...] = (9600,)
    discovery_hosts: tuple[str, ...] = ()
    discovery_cidrs: tuple[str, ...] = ()
    discovery_ports: tuple[int, ...] = (502, 8899)
    discovery_timeout_seconds: float = 1.0
    discovery_max_network_hosts: int = 256
    poll_interval_seconds: float = 5.0
    airflow_observation_seconds: float = 0.0
    airflow_observation_interval_seconds: float = 1.0
    api_bind: str = "127.0.0.1"
    api_port: int = 8000
    api_token: str | None = None
    api_cors_origins: tuple[str, ...] = ()
    database_url: str = "sqlite:///./thessla.db"
    telemetry_retention_rows: int = 10000
    audit_retention_rows: int = 5000
    command_cache_retention_rows: int = 256
    command_cache_ttl_seconds: float = 86400.0

    def __post_init__(self) -> None:
        if not 1 <= self.device_id <= 247:
            raise ValueError("device_id must be in the range 1..247")
        if not self.discovery_device_ids or any(
            not 1 <= device_id <= 247 for device_id in self.discovery_device_ids
        ):
            raise ValueError("discovery_device_ids must contain Modbus IDs in 1..247")
        if any(baud <= 0 for baud in self.discovery_bauds):
            raise ValueError("discovery baud rates must be positive")
        if self.discovery_timeout_seconds <= 0:
            raise ValueError("discovery timeout must be positive")
        if self.discovery_max_network_hosts < 1:
            raise ValueError("discovery_max_network_hosts must be positive")
        if self.airflow_observation_seconds < 0:
            raise ValueError("airflow_observation_seconds cannot be negative")
        if self.airflow_observation_interval_seconds <= 0:
            raise ValueError("airflow_observation_interval_seconds must be positive")
        if (
            self.telemetry_retention_rows < 1
            or self.audit_retention_rows < 1
            or self.command_cache_retention_rows < 1
        ):
            raise ValueError("history retention limits must be positive")
        if self.command_cache_ttl_seconds <= 0:
            raise ValueError("command cache TTL must be positive")
        if "*" in self.api_cors_origins:
            raise ValueError("api_cors_origins must contain explicit origins, not '*'")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        if environ is None:
            loaded: dict[str, str] = {}
            try:
                from dotenv import dotenv_values

                loaded = {
                    key: value
                    for key, value in dotenv_values(".env").items()
                    if value is not None
                }
            except (ImportError, OSError):
                # Environment variables remain sufficient in minimal installs.
                pass
            loaded.update(os.environ)
            env: Mapping[str, str] = loaded
        else:
            env = environ

        def get(name: str, default: str) -> str:
            return env.get(name, default)

        transport = TransportKind(get("THESSLA_TRANSPORT", "serial").lower())
        serial_port = env.get("THESSLA_SERIAL_PORT")
        host = env.get("THESSLA_HOST")
        return cls(
            transport=transport,
            serial_port=serial_port,
            baudrate=int(get("THESSLA_BAUDRATE", "9600")),
            bytesize=int(get("THESSLA_BYTESIZE", "8")),
            parity=get("THESSLA_PARITY", "N").upper(),
            stopbits=int(get("THESSLA_STOPBITS", "1")),
            host=host,
            modbus_port=int(get("THESSLA_MODBUS_PORT", "502")),
            gateway_port=int(get("THESSLA_PORT", "8899")),
            device_id=int(get("THESSLA_DEVICE_ID", "10")),
            discovery_device_ids=_ints(
                get("THESSLA_DISCOVERY_DEVICE_IDS", "10"), name="THESSLA_DISCOVERY_DEVICE_IDS"
            ),
            discovery_bauds=_ints(
                get("THESSLA_DISCOVERY_BAUDS", "9600"), name="THESSLA_DISCOVERY_BAUDS"
            ),
            discovery_hosts=_csv(env.get("THESSLA_DISCOVERY_HOSTS")),
            discovery_cidrs=_csv(env.get("THESSLA_DISCOVERY_CIDRS")),
            discovery_ports=_ints(
                get("THESSLA_DISCOVERY_PORTS", "502,8899"), name="THESSLA_DISCOVERY_PORTS"
            ),
            discovery_timeout_seconds=float(get("THESSLA_DISCOVERY_TIMEOUT_SECONDS", "1.0")),
            discovery_max_network_hosts=int(get("THESSLA_DISCOVERY_MAX_HOSTS", "256")),
            poll_interval_seconds=float(get("THESSLA_POLL_INTERVAL_SECONDS", "5")),
            airflow_observation_seconds=float(
                get("THESSLA_AIRFLOW_OBSERVATION_SECONDS", "0")
            ),
            airflow_observation_interval_seconds=float(
                get("THESSLA_AIRFLOW_OBSERVATION_INTERVAL_SECONDS", "1")
            ),
            api_bind=get("THESSLA_API_BIND", "127.0.0.1"),
            api_port=int(get("THESSLA_API_PORT", "8000")),
            api_token=env.get("THESSLA_API_TOKEN") or None,
            api_cors_origins=_csv(env.get("THESSLA_API_CORS_ORIGINS")),
            database_url=get("THESSLA_DATABASE_URL", "sqlite:///./thessla.db"),
            telemetry_retention_rows=int(get("THESSLA_TELEMETRY_RETENTION_ROWS", "10000")),
            audit_retention_rows=int(get("THESSLA_AUDIT_RETENTION_ROWS", "5000")),
            command_cache_retention_rows=int(
                get("THESSLA_COMMAND_CACHE_RETENTION_ROWS", "256")
            ),
            command_cache_ttl_seconds=float(
                get("THESSLA_COMMAND_CACHE_TTL_SECONDS", "86400")
            ),
        )

    def serial_endpoint(
        self, port: str | None = None, *, baudrate: int | None = None
    ) -> TransportEndpoint:
        """Build a serial endpoint for a selected discovery candidate."""

        selected_port = port or self.serial_port
        if not selected_port:
            raise ValueError("a serial port must be selected")
        return TransportEndpoint(
            kind=TransportKind.SERIAL,
            address=selected_port,
            baudrate=baudrate or self.baudrate,
            bytesize=self.bytesize,
            parity=self.parity,
            stopbits=self.stopbits,
            timeout_seconds=self.discovery_timeout_seconds,
        )

    def tcp_endpoint(
        self, host: str | None = None, *, port: int | None = None
    ) -> TransportEndpoint:
        """Build a TCP endpoint for an explicitly selected gateway."""

        selected_host = host or self.host
        if not selected_host:
            raise ValueError("a TCP host must be selected")
        return TransportEndpoint(
            kind=TransportKind.TCP,
            address=selected_host,
            port=port or self.modbus_port,
            timeout_seconds=self.discovery_timeout_seconds,
        )
