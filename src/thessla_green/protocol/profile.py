"""Read-only identification and snapshot profile from the vendor PDF."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AirPackRegisterProfile:
    """Addresses are zero-based, as expected by PyModbus."""

    model_name: str = "AirPack4"
    firmware_address: int = 0
    firmware_minor_address: int = 1
    firmware_patch_address: int = 4
    temperature_address: int = 16
    temperature_count: int = 7
    serial_address: int = 24
    serial_count: int = 6
    airflow_address: int = 256
    airflow_count: int = 2
    percentage_address: int = 272
    percentage_count: int = 2
    flowrate_address: int = 274
    flowrate_count: int = 2
    mode_address: int = 4208
    # mode, season, manual intensity and temporary intensity (4208..4211)
    mode_count: int = 4
    comfort_address: int = 4304
    bypass_off_address: int = 4320
    bypass_status_address: int = 4330
    on_off_address: int = 4387


AIRPACK4_PROFILE = AirPackRegisterProfile()
