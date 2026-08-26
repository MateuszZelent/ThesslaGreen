"""Bounded, read-only Modbus endpoint and AirPack discovery."""

from .candidates import SerialPortInfo, enumerate_serial_ports
from .probe import AirPackProbe
from .service import (
    DiscoverySelectionError,
    DiscoveryService,
    discovery_endpoints,
    select_unique_airpack,
)

__all__ = [
    "AirPackProbe",
    "DiscoveryService",
    "DiscoverySelectionError",
    "SerialPortInfo",
    "discovery_endpoints",
    "enumerate_serial_ports",
    "select_unique_airpack",
]
