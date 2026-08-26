from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import termios

import pytest

from thessla_green.domain.models import TransportEndpoint, TransportKind
from thessla_green.protocol.transport import PymodbusTransport, SerialPortBusy


class ModernPymodbusClient:
    connected = True

    async def read_input_registers(
        self, address: int, *, count: int, device_id: int
    ) -> object:
        assert (address, count, device_id) == (0, 5, 10)
        return type("Response", (), {"registers": [4, 84, 0, 0, 2]})()

    async def write_register(self, address: int, value: int, *, device_id: int) -> object:
        assert (address, value, device_id) == (4210, 60, 10)
        return type("Response", (), {"address": address})()

    async def write_registers(
        self, address: int, values: list[int], *, device_id: int
    ) -> object:
        assert (address, values, device_id) == (4400, [2, 70, 1], 10)
        return type("Response", (), {"address": address})()


class LegacyPymodbusClient:
    connected = True

    async def read_input_registers(
        self, address: int, count: int, *, slave: int
    ) -> object:
        assert (address, count, slave) == (0, 5, 10)
        return type("Response", (), {"registers": [4, 84, 0, 0, 2]})()


def test_transport_uses_keyword_count_with_modern_pymodbus() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        transport = PymodbusTransport(endpoint)
        transport._client = ModernPymodbusClient()

        assert await transport.read_input_registers(0, 5, 10) == (4, 84, 0, 0, 2)
        await transport.write_holding_register(4210, 60, 10)
        await transport.write_holding_registers(4400, (2, 70, 1), 10)

    asyncio.run(run())


def test_transport_falls_back_to_legacy_slave_keyword() -> None:
    async def run() -> None:
        endpoint = TransportEndpoint(TransportKind.SERIAL, "/dev/ttyTEST")
        transport = PymodbusTransport(endpoint)
        transport._client = LegacyPymodbusClient()

        assert await transport.read_input_registers(0, 5, 10) == (4, 84, 0, 0, 2)

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="TTY exclusive locks are POSIX-specific")
def test_serial_lock_preflight_does_not_leave_terminal_exclusive() -> None:
    master, slave = pty.openpty()
    path = os.ttyname(slave)
    os.close(slave)
    try:
        PymodbusTransport._check_serial_lock(path)
        descriptor = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        os.close(descriptor)
    finally:
        os.close(master)


@pytest.mark.skipif(os.name != "posix", reason="TTY exclusive locks are POSIX-specific")
def test_serial_lock_preflight_classifies_an_existing_exclusive_owner() -> None:
    master, slave = pty.openpty()
    path = os.ttyname(slave)
    try:
        fcntl.ioctl(slave, termios.TIOCEXCL)
        with pytest.raises(SerialPortBusy):
            PymodbusTransport._check_serial_lock(path)
    finally:
        # Clear the flag before closing so the pseudo-terminal is reusable
        # when the test runner keeps the master descriptor alive briefly.
        try:
            fcntl.ioctl(slave, termios.TIOCNXCL)
        finally:
            os.close(slave)
            os.close(master)
