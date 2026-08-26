"""Bounded endpoint generation and concurrent, read-only probing."""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Callable, Iterable

from custom_components.thessla_green._core.config import Settings
from custom_components.thessla_green._core.discovery.candidates import (
    SerialPortInfo,
    enumerate_serial_ports,
)
from custom_components.thessla_green._core.discovery.probe import AirPackProbe
from custom_components.thessla_green._core.domain.models import (
    DiscoveryResult,
    ProbeStatus,
    TransportEndpoint,
    TransportKind,
)
from custom_components.thessla_green._core.protocol.transport import (
    ModbusTransport,
    PymodbusTransport,
    SerialPortBusy,
    is_serial_port_busy_error,
)

TransportFactory = Callable[[TransportEndpoint], ModbusTransport]


class DiscoverySelectionError(RuntimeError):
    """Raised when automatic startup cannot choose one safe AirPack result."""

    def __init__(self, results: tuple[DiscoveryResult, ...]) -> None:
        selectable = tuple(result for result in results if result.is_selectable)
        if not selectable:
            message = "automatic discovery found no confirmed AirPack device"
        else:
            message = (
                "automatic discovery found multiple confirmed AirPack devices; "
                "select an endpoint explicitly"
            )
        super().__init__(message)
        self.results = results


def select_unique_airpack(results: Iterable[DiscoveryResult]) -> DiscoveryResult:
    """Return the only selectable result or fail closed for zero/many devices."""

    normalized = tuple(results)
    selectable = tuple(result for result in normalized if result.is_selectable)
    if len(selectable) != 1:
        raise DiscoverySelectionError(normalized)
    return selectable[0]


def _network_hosts(cidr: str, maximum: int) -> tuple[str, ...]:
    network = ipaddress.ip_network(cidr, strict=False)
    hosts = tuple(str(host) for host in network.hosts())
    if len(hosts) > maximum:
        raise ValueError(
            f"discovery network {cidr} contains {len(hosts)} hosts; maximum is {maximum}"
        )
    return hosts


def discovery_endpoints(
    settings: Settings,
    *,
    serial_ports: Iterable[SerialPortInfo] | None = None,
) -> tuple[TransportEndpoint, ...]:
    """Build deduplicated candidates without opening a port or socket."""

    endpoints: list[TransportEndpoint] = []
    seen: set[str] = set()

    def add(endpoint: TransportEndpoint) -> None:
        if endpoint.key not in seen:
            seen.add(endpoint.key)
            endpoints.append(endpoint)

    if settings.serial_port:
        # An explicit path is authoritative. This is important for stable
        # /dev/serial/by-id/... symlinks and avoids probing unrelated ports.
        selected_serial_ports = [SerialPortInfo(settings.serial_port, "configured")]
    else:
        selected_serial_ports = (
            list(serial_ports) if serial_ports is not None else list(enumerate_serial_ports())
        )
    for serial_port in selected_serial_ports:
        for baudrate in settings.discovery_bauds:
            add(settings.serial_endpoint(serial_port.device, baudrate=baudrate))

    hosts = list(settings.discovery_hosts)
    if settings.host:
        hosts.append(settings.host)
    for cidr in settings.discovery_cidrs:
        hosts.extend(_network_hosts(cidr, settings.discovery_max_network_hosts))
    for host in hosts:
        for tcp_port in settings.discovery_ports:
            add(settings.tcp_endpoint(host, port=tcp_port))

    return tuple(endpoints)


class DiscoveryService:
    """Discover ports/gateways and AirPack devices without writing registers."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport_factory: TransportFactory | None = None,
        probe: AirPackProbe | None = None,
        max_concurrency: int = 8,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.settings = settings
        self.transport_factory = transport_factory or PymodbusTransport
        self.probe = probe or AirPackProbe()
        self.max_concurrency = max_concurrency

    async def discover(
        self,
        *,
        serial_ports: Iterable[SerialPortInfo] | None = None,
        endpoints: Iterable[TransportEndpoint] | None = None,
        unit_ids: Iterable[int] | None = None,
    ) -> tuple[DiscoveryResult, ...]:
        candidates = (
            tuple(endpoints)
            if endpoints is not None
            else discovery_endpoints(self.settings, serial_ports=serial_ports)
        )
        selected_unit_ids = tuple(unit_ids or self.settings.discovery_device_ids)
        if any(not 1 <= unit_id <= 247 for unit_id in selected_unit_ids):
            raise ValueError("unit IDs must be in the range 1..247")
        if not candidates:
            return ()

        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def probe_endpoint(endpoint: TransportEndpoint) -> list[DiscoveryResult]:
            async with semaphore:
                results: list[DiscoveryResult] = []
                # A serial bus must be probed sequentially; the same rule is
                # harmless for TCP and keeps fake transports deterministic.
                # Connect once per endpoint so a unit-id scan does not reopen
                # the same serial device for every candidate address.
                transport = self.transport_factory(endpoint)
                try:
                    await transport.connect()
                except PermissionError as exc:
                    results.extend(
                        self._connection_error(
                            endpoint, unit_id, ProbeStatus.PERMISSION_DENIED, exc
                        )
                        for unit_id in selected_unit_ids
                    )
                except FileNotFoundError as exc:
                    results.extend(
                        self._connection_error(endpoint, unit_id, ProbeStatus.DEVICE_NOT_FOUND, exc)
                        for unit_id in selected_unit_ids
                    )
                except SerialPortBusy as exc:
                    results.extend(
                        self._connection_error(endpoint, unit_id, ProbeStatus.PORT_BUSY, exc)
                        for unit_id in selected_unit_ids
                    )
                except OSError as exc:
                    status = (
                        ProbeStatus.PORT_BUSY
                        if endpoint.kind is TransportKind.SERIAL and is_serial_port_busy_error(exc)
                        else ProbeStatus.NO_RESPONSE
                    )
                    results.extend(
                        self._connection_error(endpoint, unit_id, status, exc)
                        for unit_id in selected_unit_ids
                    )
                except TimeoutError as exc:
                    results.extend(
                        self._connection_error(endpoint, unit_id, ProbeStatus.NO_RESPONSE, exc)
                        for unit_id in selected_unit_ids
                    )
                except Exception as exc:
                    results.extend(
                        self._connection_error(endpoint, unit_id, ProbeStatus.ERROR, exc)
                        for unit_id in selected_unit_ids
                    )
                else:
                    for unit_id in selected_unit_ids:
                        try:
                            results.append(await self.probe.run(transport, endpoint, unit_id))
                        except Exception as exc:
                            results.append(
                                self._connection_error(endpoint, unit_id, ProbeStatus.ERROR, exc)
                            )
                finally:
                    await transport.close()
                return results

        nested = await asyncio.gather(*(probe_endpoint(endpoint) for endpoint in candidates))
        return tuple(result for group in nested for result in group)

    @staticmethod
    def _connection_error(
        endpoint: TransportEndpoint,
        unit_id: int,
        status: ProbeStatus,
        error: BaseException,
    ) -> DiscoveryResult:
        message = str(error)
        if status is ProbeStatus.PERMISSION_DENIED:
            message = (
                f"{message}; verify the service user is in dialout/uucp "
                "and that the configured path is accessible"
            )
        return DiscoveryResult(
            endpoint=endpoint,
            unit_id=unit_id,
            status=status,
            error=message,
        )
