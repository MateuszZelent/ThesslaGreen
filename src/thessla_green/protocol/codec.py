"""Pure codecs for values documented by the AirPack4 protocol."""

from __future__ import annotations

from collections.abc import Sequence

MISSING_SENSOR_VALUE = 0x8000


def decode_int16(raw: int, *, missing_value: int = MISSING_SENSOR_VALUE) -> int | None:
    """Decode one unsigned Modbus word as signed int16.

    The vendor uses ``0x8000`` as a missing temperature marker, which is
    handled before two's-complement conversion.
    """

    if not 0 <= raw <= 0xFFFF:
        raise ValueError("raw register value must be in the range 0..65535")
    if raw == missing_value:
        return None
    return raw - 0x10000 if raw & 0x8000 else raw


def decode_scaled_int16(raw: int, scale: float = 1.0) -> float | None:
    value = decode_int16(raw)
    return None if value is None else value * scale


def decode_firmware_version(values: Sequence[int]) -> tuple[int, int, int]:
    """Decode registers 0x0000, 0x0001 and 0x0004 as ``MM.mm.pp``."""

    if len(values) != 3:
        raise ValueError("firmware requires major, minor, and patch values")
    if any(not 0 <= value <= 0xFFFF for value in values):
        raise ValueError("firmware words must be uint16")
    return int(values[0]), int(values[1]), int(values[2])


def decode_serial_number(values: Sequence[int]) -> str:
    """Render the six vendor serial words in the documented hexadecimal form."""

    if len(values) != 6:
        raise ValueError("AirPack serial number requires six registers")
    if any(not 0 <= value <= 0xFFFF for value in values):
        raise ValueError("serial words must be uint16")
    if all(value in (0, 0xFFFF) for value in values):
        return ""
    return " ".join(f"{value:04x}" for value in values)
