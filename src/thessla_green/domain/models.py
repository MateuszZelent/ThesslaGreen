"""Stable data contracts shared by protocol and application adapters.

The module intentionally uses only the Python standard library.  FastAPI,
Home Assistant, and PyModbus are transport/adaptor concerns and must not leak
into these models.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class TransportKind(StrEnum):
    """Physical or network transport used to reach a Modbus server."""

    SERIAL = "serial"
    TCP = "tcp"


@dataclass(frozen=True, slots=True)
class TransportEndpoint:
    """A fully specified connection endpoint.

    ``address`` is a serial device path for RTU and a hostname/IP for TCP.
    ``port`` is required only for TCP.  The object is immutable so it can be
    safely used as a discovery key.
    """

    kind: TransportKind
    address: str
    port: int | None = None
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: int = 1
    timeout_seconds: float = 1.5

    def __post_init__(self) -> None:
        if not self.address.strip():
            raise ValueError("transport address cannot be empty")
        if self.kind is TransportKind.TCP:
            if self.port is None or not 1 <= self.port <= 65535:
                raise ValueError("TCP endpoint requires a valid port")
        elif self.port is not None:
            raise ValueError("serial endpoint must not define a TCP port")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    @property
    def key(self) -> str:
        """Stable, human-readable endpoint key for logs and deduplication."""

        if self.kind is TransportKind.TCP:
            return f"tcp://{self.address}:{self.port}"
        return f"serial://{self.address}"

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "kind": self.kind.value,
            "address": self.address,
            "key": self.key,
            "timeout_seconds": self.timeout_seconds,
        }
        if self.kind is TransportKind.TCP:
            data["port"] = self.port
        else:
            data.update(
                baudrate=self.baudrate,
                bytesize=self.bytesize,
                parity=self.parity,
                stopbits=self.stopbits,
            )
        return data


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """Identity extracted from read-only vendor registers."""

    model: str
    unit_id: int
    firmware: tuple[int, int, int] | None = None
    serial_number: str | None = None
    endpoint: TransportEndpoint | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.unit_id <= 247:
            raise ValueError("Modbus unit_id must be in the range 1..247")
        if self.firmware is not None and any(part < 0 for part in self.firmware):
            raise ValueError("firmware version parts cannot be negative")

    @property
    def stable_id(self) -> str:
        """Stable device key, preferring the vendor serial number."""

        if self.serial_number:
            groups = self.serial_number.lower().split()
            # Since 0.2.2 the public serial follows the PDF (three groups made
            # from six bytes). Preserve the legacy six-word token so existing
            # Home Assistant unique IDs do not change after the codec fix.
            if len(groups) == 3 and all(len(group) == 4 for group in groups):
                groups = [
                    f"00{group[offset:offset + 2]}"
                    for group in groups
                    for offset in (0, 2)
                ]
            return f"{self.model.lower()}-{'-'.join(groups)}-{self.unit_id}"
        endpoint = self.endpoint.key if self.endpoint else "unknown"
        # Keep the fallback safe for URL path segments and Home Assistant IDs.
        endpoint_id = endpoint.replace("://", "-").replace("/", "-").replace(":", "-")
        return f"{self.model.lower()}-{endpoint_id}-{self.unit_id}"

    @property
    def firmware_string(self) -> str | None:
        if self.firmware is None:
            return None
        return ".".join(str(part) for part in self.firmware)

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "unit_id": self.unit_id,
            "firmware": self.firmware_string,
            "serial_number": self.serial_number,
            "endpoint": self.endpoint.to_dict() if self.endpoint else None,
            "stable_id": self.stable_id,
        }


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Capabilities advertised by the selected model/firmware profile."""

    features: frozenset[str] = frozenset()
    min_fan_percentage: int = 10
    max_fan_percentage: int = 100

    def __post_init__(self) -> None:
        if not 0 <= self.min_fan_percentage <= self.max_fan_percentage <= 150:
            raise ValueError("fan percentage bounds are invalid")

    def supports(self, feature: str) -> bool:
        return feature in self.features

    def to_dict(self) -> dict[str, object]:
        return {
            "features": sorted(self.features),
            "min_fan_percentage": self.min_fan_percentage,
            "max_fan_percentage": self.max_fan_percentage,
        }


@dataclass(frozen=True, slots=True)
class DeviceState:
    """Immutable normalized snapshot returned to every adapter."""

    revision: int
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    online: bool = False
    identity: DeviceIdentity | None = None
    capabilities: Capabilities = field(default_factory=Capabilities)
    values: Mapping[str, object] = field(default_factory=dict)
    quality: str = "unknown"
    error: str | None = None

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("state revision cannot be negative")
        if self.captured_at.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")

    def to_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "captured_at": self.captured_at.isoformat(),
            "online": self.online,
            "identity": self.identity.to_dict() if self.identity else None,
            "capabilities": self.capabilities.to_dict(),
            "values": dict(self.values),
            "quality": self.quality,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Evidence for one attempted typed register write.

    The in-memory event is the first audit boundary.  A persistent event
    store can consume the same immutable contract later without changing the
    protocol or adapter layers.
    """

    sequence: int
    captured_at: datetime
    source: str
    command: str
    register: str
    address: int
    requested_value: int
    confirmed_value: int | None
    success: bool
    endpoint: TransportEndpoint
    unit_id: int
    error: str | None = None

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("audit sequence must be positive")
        if not self.source.strip():
            raise ValueError("audit source cannot be empty")
        if self.address < 0:
            raise ValueError("audit register address cannot be negative")
        if not 1 <= self.unit_id <= 247:
            raise ValueError("audit unit_id must be in the range 1..247")
        if self.captured_at.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "captured_at": self.captured_at.isoformat(),
            "source": self.source,
            "command": self.command,
            "register": self.register,
            "address": self.address,
            "requested_value": self.requested_value,
            "confirmed_value": self.confirmed_value,
            "success": self.success,
            "endpoint": self.endpoint.to_dict(),
            "unit_id": self.unit_id,
            "error": self.error,
        }


class ProbeStatus(StrEnum):
    """Outcome categories returned by discovery."""

    AIRPACK = "airpack"
    UNKNOWN_MODBUS_DEVICE = "unknown_modbus_device"
    # Backward-compatible Python name for callers of the first prototype.
    MODBUS_DEVICE = UNKNOWN_MODBUS_DEVICE
    NO_RESPONSE = "no_response"
    PERMISSION_DENIED = "permission_denied"
    DEVICE_NOT_FOUND = "device_not_found"
    PORT_BUSY = "port_busy"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Evidence-backed result for one endpoint/unit-id probe."""

    endpoint: TransportEndpoint
    unit_id: int
    status: ProbeStatus
    identity: DeviceIdentity | None = None
    evidence: Mapping[str, object] = field(default_factory=dict)
    error: str | None = None

    @property
    def is_selectable(self) -> bool:
        return self.status is ProbeStatus.AIRPACK and self.identity is not None

    @property
    def modbus_verified(self) -> bool:
        """Whether the endpoint returned a valid Modbus application response."""

        return self.status in {
            ProbeStatus.AIRPACK,
            ProbeStatus.UNKNOWN_MODBUS_DEVICE,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "endpoint": self.endpoint.to_dict(),
            "unit_id": self.unit_id,
            "status": self.status.value,
            "identity": self.identity.to_dict() if self.identity else None,
            "evidence": dict(self.evidence),
            "error": self.error,
            "is_selectable": self.is_selectable,
            "modbus_verified": self.modbus_verified,
        }
