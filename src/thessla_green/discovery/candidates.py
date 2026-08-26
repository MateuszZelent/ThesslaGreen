"""Local serial-port enumeration kept separate from protocol probing."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SERIAL_BY_ID_DIR = Path("/dev/serial/by-id")


@dataclass(frozen=True, slots=True)
class SerialPortInfo:
    device: str
    description: str = ""
    hwid: str = ""
    vid: int | None = None
    pid: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "device": self.device,
            "description": self.description,
            "hwid": self.hwid,
            "vid": self.vid,
            "pid": self.pid,
        }


def enumerate_serial_ports() -> tuple[SerialPortInfo, ...]:
    """Return OS-reported serial ports without opening any of them.

    PySerial is an optional import for offline model/tests; a missing package
    simply means no local serial candidates are available.
    """

    try:
        from serial.tools import list_ports  # type: ignore[import-untyped]
    except ImportError:
        return ()

    aliases = _stable_serial_aliases()
    result: list[SerialPortInfo] = []
    for port in list_ports.comports():
        device = str(port.device)
        # PySerial normally reports /dev/ttyUSB0. Prefer the stable udev
        # symlink when it exists so discovery output can be copied verbatim
        # into THESSLA_SERIAL_PORT and survives USB re-enumeration.
        device = aliases.get(os.path.realpath(device), device)
        result.append(
            SerialPortInfo(
                device=device,
                description=str(port.description or ""),
                hwid=str(port.hwid or ""),
                vid=getattr(port, "vid", None),
                pid=getattr(port, "pid", None),
            )
        )
    return tuple(sorted(result, key=lambda item: item.device))


def _stable_serial_aliases(
    alias_directory: Path = SERIAL_BY_ID_DIR,
) -> dict[str, str]:
    """Map a real serial device path to its stable udev ``by-id`` alias."""

    try:
        candidates = sorted(alias_directory.iterdir())
    except OSError:
        return {}

    aliases: dict[str, str] = {}
    for alias in candidates:
        try:
            if not alias.is_symlink():
                continue
            target = os.path.realpath(alias)
        except OSError:
            continue
        # Keep deterministic output if a USB adapter has multiple aliases.
        aliases.setdefault(target, str(alias))
    return aliases
