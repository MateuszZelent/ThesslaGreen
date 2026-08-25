"""Preliminary Modbus register catalogue.

Every address must be confirmed against the exact controller model and firmware
before writes are enabled. This module deliberately contains metadata only; the
transport and write-safety logic will be implemented separately.
"""

from dataclasses import dataclass
from enum import StrEnum


class RegisterArea(StrEnum):
    INPUT = "input"
    HOLDING = "holding"
    COIL = "coil"


@dataclass(frozen=True, slots=True)
class RegisterDefinition:
    key: str
    address: int
    area: RegisterArea
    unit: str | None = None
    scale: float = 1.0
    writable: bool = False
    minimum: int | None = None
    maximum: int | None = None


REGISTERS: tuple[RegisterDefinition, ...] = (
    RegisterDefinition("outdoor_temperature", 16, RegisterArea.INPUT, "°C", 0.1),
    RegisterDefinition("supply_temperature", 17, RegisterArea.INPUT, "°C", 0.1),
    RegisterDefinition("extract_temperature", 18, RegisterArea.INPUT, "°C", 0.1),
    RegisterDefinition("fpx_temperature", 19, RegisterArea.INPUT, "°C", 0.1),
    RegisterDefinition("pcb_temperature", 22, RegisterArea.INPUT, "°C", 0.1),
    RegisterDefinition("supply_airflow", 256, RegisterArea.HOLDING, "m³/h"),
    RegisterDefinition("extract_airflow", 257, RegisterArea.HOLDING, "m³/h"),
    RegisterDefinition("operating_state", 4208, RegisterArea.HOLDING),
    RegisterDefinition("season", 4209, RegisterArea.HOLDING, writable=True, minimum=0, maximum=1),
    RegisterDefinition("manual_fan_speed", 4210, RegisterArea.HOLDING, "%", writable=True, minimum=0, maximum=100),
    RegisterDefinition("special_mode", 4224, RegisterArea.HOLDING, writable=True),
    RegisterDefinition("comfort_mode", 4304, RegisterArea.HOLDING, writable=True, minimum=0, maximum=1),
    RegisterDefinition("bypass", 4320, RegisterArea.HOLDING, writable=True, minimum=0, maximum=1),
    RegisterDefinition("power", 4387, RegisterArea.HOLDING, writable=True, minimum=0, maximum=1),
    RegisterDefinition("erv_state", 4704, RegisterArea.HOLDING),
    RegisterDefinition("erv_mode", 4711, RegisterArea.HOLDING, writable=True, minimum=0, maximum=2),
)

