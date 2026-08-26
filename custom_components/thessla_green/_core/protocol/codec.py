"""Pure codecs for values documented by the AirPack4 protocol."""

from __future__ import annotations

from collections.abc import Sequence

MISSING_SENSOR_VALUE = 0x8000
UNAVAILABLE_AIRFLOW_VALUE = 0xFFFF
MIN_AIRPACK_TEMPERATURE_RAW = -999
MAX_AIRPACK_TEMPERATURE_RAW = 999


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


def decode_airpack_temperature(raw: int) -> float | None:
    """Decode one AirPack temperature and enforce the documented raw range."""

    value = decode_int16(raw)
    if value is None:
        return None
    if not MIN_AIRPACK_TEMPERATURE_RAW <= value <= MAX_AIRPACK_TEMPERATURE_RAW:
        raise ValueError("AirPack temperature must be 0x8000 or in the raw range -999..999")
    # Division by the documented integer scale avoids exposing artifacts such
    # as ``17.900000000000002`` in JSON and UI snapshots.
    return value / 10.0


def decode_airflow(raw: int) -> int | None:
    """Decode measured airflow; ``0xffff`` means Constant Flow is inactive."""

    if not 0 <= raw <= 0xFFFF:
        raise ValueError("airflow register value must be in the range 0..65535")
    return None if raw == UNAVAILABLE_AIRFLOW_VALUE else raw


def decode_firmware_version(values: Sequence[int]) -> tuple[int, int, int]:
    """Decode registers 0x0000, 0x0001 and 0x0004 as ``MM.mm.pp``."""

    if len(values) != 3:
        raise ValueError("firmware requires major, minor, and patch values")
    if any(not 0 <= value <= 0xFFFF for value in values):
        raise ValueError("firmware words must be uint16")
    return int(values[0]), int(values[1]), int(values[2])


def decode_serial_number(values: Sequence[int]) -> str:
    """Combine six documented serial bytes into three hexadecimal groups.

    The PDF example maps ``001a 002b 003c 004d 005e 006f`` to
    ``1a2b 3c4d 5e6f``.  Although transported in Modbus words, every serial
    component is therefore one byte and its high byte must be zero.
    """

    if len(values) != 6:
        raise ValueError("AirPack serial number requires six registers")
    if all(value in (0, 0xFFFF) for value in values):
        return ""
    if any(not 0 <= value <= 0xFF for value in values):
        raise ValueError("AirPack serial components must be bytes stored in Modbus words")
    return " ".join(f"{values[index]:02x}{values[index + 1]:02x}" for index in range(0, 6, 2))
