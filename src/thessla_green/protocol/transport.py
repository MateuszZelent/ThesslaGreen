"""Transport abstraction and lazy PyModbus implementation."""

from __future__ import annotations

import asyncio
import errno
import os
from collections.abc import Sequence
from typing import Any, Protocol

from thessla_green.domain.models import TransportEndpoint, TransportKind


class ModbusTransportError(RuntimeError):
    """Base class for transport and protocol failures."""


class PymodbusUnavailable(ModbusTransportError):
    """Raised when the optional runtime dependency is not installed."""


class ReadResponseError(ModbusTransportError):
    """Raised when a Modbus response is an exception or malformed."""


class SerialPortBusy(ModbusTransportError):
    """Raised when another process owns the serial port exclusively."""


def is_serial_port_busy_error(error: BaseException) -> bool:
    """Return whether an OS/driver error describes an exclusive TTY lock.

    PyModbus normally performs the ``exclusive=True`` open inside its async
    client.  Depending on the release, that failure is either raised as an
    ``OSError`` or logged and returned as ``False``.  Discovery uses this
    helper for the raised form so a lock is not reported as an unexplained
    communication timeout.
    """

    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, SerialPortBusy):
            return True
        if isinstance(current, OSError) and current.errno in {errno.EAGAIN, errno.EBUSY}:
            return True
        message = str(current).lower()
        if "exclusively lock" in message or (
            "resource temporarily unavailable" in message and "port" in message
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


class ModbusTransport(Protocol):
    """Small async interface used by discovery and application services."""

    endpoint: TransportEndpoint

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def read_input_registers(
        self, address: int, count: int, unit_id: int
    ) -> tuple[int, ...]: ...

    async def read_holding_registers(
        self, address: int, count: int, unit_id: int
    ) -> tuple[int, ...]: ...

    async def read_coils(self, address: int, count: int, unit_id: int) -> tuple[bool, ...]: ...

    async def read_discrete_inputs(
        self, address: int, count: int, unit_id: int
    ) -> tuple[bool, ...]: ...

    async def write_holding_register(self, address: int, value: int, unit_id: int) -> None: ...


def _is_error(response: Any) -> bool:
    checker = getattr(response, "isError", None)
    return bool(checker()) if callable(checker) else False


class PymodbusTransport:
    """Async PyModbus adapter.

    PyModbus is imported only when a real connection is requested. This keeps
    discovery/model unit tests runnable in environments that have not installed
    hardware dependencies yet.
    """

    def __init__(self, endpoint: TransportEndpoint, *, retries: int = 1) -> None:
        self.endpoint = endpoint
        self.retries = retries
        self._client: Any | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._client is not None:
            return
        if self.endpoint.kind is TransportKind.SERIAL:
            self._validate_serial_device()
        try:
            from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
            from pymodbus.framer import FramerType
        except ImportError as exc:  # pragma: no cover - exercised in deployment, not unit tests
            raise PymodbusUnavailable(
                "PyModbus and its serial dependency are required for live discovery"
            ) from exc

        common: dict[str, Any] = {
            "timeout": self.endpoint.timeout_seconds,
            "retries": self.retries,
            "reconnect_delay": 0,
        }
        if self.endpoint.kind is TransportKind.SERIAL:
            self._client = AsyncModbusSerialClient(
                port=self.endpoint.address,
                # PyModbus 3.11+ calls the old ``method="rtu"`` argument
                # ``framer``.  RTU is also the default, but spelling it out
                # makes the wire protocol explicit and avoids ASCII fallback.
                framer=FramerType.RTU,
                baudrate=self.endpoint.baudrate,
                bytesize=self.endpoint.bytesize,
                parity=self.endpoint.parity,
                stopbits=self.endpoint.stopbits,
                **common,
            )
        else:
            if self.endpoint.port is None:  # guarded by TransportEndpoint validation
                raise ValueError("TCP endpoint requires a port")
            self._client = AsyncModbusTcpClient(
                host=self.endpoint.address,
                port=self.endpoint.port,
                **common,
            )

        try:
            connected = await self._client.connect()
            if connected is False and not bool(getattr(self._client, "connected", False)):
                # PyModbus catches the serial ``EBUSY`` raised by pyserial,
                # logs it, and returns False. Re-check the exclusive lock so
                # a race between the preflight and the real open keeps the
                # actionable ``port_busy`` status.
                if self.endpoint.kind is TransportKind.SERIAL:
                    try:
                        self._check_serial_lock(self.endpoint.address)
                    except SerialPortBusy as exc:
                        raise SerialPortBusy(
                            f"serial port is busy: {self.endpoint.address}"
                        ) from exc
                raise ModbusTransportError(f"unable to connect to {self.endpoint.key}")
        except OSError as exc:
            busy = self.endpoint.kind is TransportKind.SERIAL and is_serial_port_busy_error(exc)
            await self.close()
            if busy:
                raise SerialPortBusy(f"serial port is busy: {self.endpoint.address}") from exc
            raise
        except Exception:
            await self.close()
            raise

    def _validate_serial_device(self) -> None:
        """Fail before PyModbus opens a port, with an actionable OS error."""

        path = self.endpoint.address
        try:
            os.stat(path)
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"serial device not found: {path}") from exc
        except PermissionError as exc:
            raise PermissionError(f"permission denied reading serial device: {path}") from exc

        if not os.access(path, os.R_OK | os.W_OK):
            raise PermissionError(
                f"permission denied opening {path}; add the runtime user to the "
                "dialout or uucp group"
            )
        self._check_serial_lock(path)

    @staticmethod
    def _check_serial_lock(path: str) -> None:
        """Check an exclusive TTY lock without changing the device state.

        ``TIOCEXCL`` is a mutating ioctl: issuing it during a preflight check
        can leave a free terminal exclusive and make the real client report
        ``EBUSY``.  Opening the device without that ioctl is sufficient to
        detect an existing exclusive owner while keeping the check reversible.
        The actual Modbus client still owns the final open/connect race.
        """

        if os.name != "posix":
            return

        flags = os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            if exc.errno in {errno.EAGAIN, errno.EBUSY}:
                raise SerialPortBusy(f"serial port is busy: {path}") from exc
            raise
        os.close(descriptor)

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            result = client.close()
            if asyncio.iscoroutine(result):
                await result

    async def _request(self, method: str, *args: Any, unit_id: int, **kwargs: Any) -> Any:
        if self._client is None:
            raise ModbusTransportError("transport is not connected")
        async with self._lock:
            operation = getattr(self._client, method)
            # PyModbus 3.11 uses device_id; older supported releases use slave.
            try:
                response = await operation(*args, device_id=unit_id, **kwargs)
            except TypeError as exc:
                if "device_id" not in str(exc) and "unexpected keyword" not in str(exc):
                    raise
                response = await operation(*args, slave=unit_id, **kwargs)
        if _is_error(response):
            raise ReadResponseError(f"{method} returned a Modbus exception: {response!s}")
        return response

    @staticmethod
    def _values(response: Any, attribute: str) -> tuple[Any, ...]:
        values = getattr(response, attribute, None)
        if values is None:
            raise ReadResponseError(f"Modbus response has no {attribute} payload")
        return tuple(values)

    async def read_input_registers(self, address: int, count: int, unit_id: int) -> tuple[int, ...]:
        response = await self._request(
            "read_input_registers", address, count=count, unit_id=unit_id
        )
        return tuple(int(value) for value in self._values(response, "registers"))

    async def read_holding_registers(
        self, address: int, count: int, unit_id: int
    ) -> tuple[int, ...]:
        response = await self._request(
            "read_holding_registers", address, count=count, unit_id=unit_id
        )
        return tuple(int(value) for value in self._values(response, "registers"))

    async def read_coils(self, address: int, count: int, unit_id: int) -> tuple[bool, ...]:
        response = await self._request("read_coils", address, count=count, unit_id=unit_id)
        return tuple(bool(value) for value in self._values(response, "bits"))[:count]

    async def read_discrete_inputs(
        self, address: int, count: int, unit_id: int
    ) -> tuple[bool, ...]:
        response = await self._request(
            "read_discrete_inputs", address, count=count, unit_id=unit_id
        )
        return tuple(bool(value) for value in self._values(response, "bits"))[:count]

    async def write_holding_register(self, address: int, value: int, unit_id: int) -> None:
        response = await self._request(
            "write_register", address, value, unit_id=unit_id
        )
        if not hasattr(response, "address"):
            raise ReadResponseError("write response did not contain an address")


def ensure_register_count(values: Sequence[int], count: int) -> tuple[int, ...]:
    """Validate a response length at the protocol boundary."""

    normalized = tuple(int(value) for value in values)
    if len(normalized) != count:
        raise ReadResponseError(f"expected {count} registers, received {len(normalized)}")
    return normalized
