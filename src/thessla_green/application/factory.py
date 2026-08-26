"""Runtime wiring for the gateway profile."""

from __future__ import annotations

from thessla_green.application.gateway import GatewayService
from thessla_green.config import Settings
from thessla_green.domain.models import TransportEndpoint, TransportKind
from thessla_green.protocol.transport import PymodbusTransport
from thessla_green.storage import SQLiteStore


def build_gateway_for_endpoint(
    settings: Settings,
    endpoint: TransportEndpoint,
    *,
    unit_id: int,
) -> GatewayService:
    """Build the single-owner gateway for an already selected endpoint."""

    transport = PymodbusTransport(endpoint)
    return GatewayService(
        transport,
        endpoint=endpoint,
        unit_id=unit_id,
        store=SQLiteStore(
            settings.database_url,
            max_state_rows=settings.telemetry_retention_rows,
            max_audit_rows=settings.audit_retention_rows,
            max_command_rows=settings.command_cache_retention_rows,
        ),
        command_cache_limit=settings.command_cache_retention_rows,
        command_cache_ttl_seconds=settings.command_cache_ttl_seconds,
        airflow_observation_seconds=settings.airflow_observation_seconds,
        airflow_observation_interval_seconds=settings.airflow_observation_interval_seconds,
    )


def build_gateway(settings: Settings) -> GatewayService | None:
    """Build a gateway only when the user explicitly selected an endpoint.

    Automatic discovery is deliberately not run as a side effect of starting
    the API. The user selects a read-only discovery result first, then stores
    its endpoint in configuration.
    """

    if settings.transport is TransportKind.SERIAL:
        if not settings.serial_port:
            return None
        endpoint = settings.serial_endpoint()
    else:
        if not settings.host:
            return None
        endpoint = settings.tcp_endpoint(port=settings.modbus_port)
    return build_gateway_for_endpoint(settings, endpoint, unit_id=settings.device_id)
