"""Register catalogue backed by the AirPack4 vendor protocol PDF.

Only the small, verified subset needed by the first controller slice is
included here. Addresses use the zero-based notation accepted by PyModbus.
Discovery and telemetry registers are read-only; control registers are marked
explicitly as writable and remain subject to application-level validation.
"""

from dataclasses import dataclass
from enum import StrEnum


class RegisterArea(StrEnum):
    INPUT = "input"
    HOLDING = "holding"
    COIL = "coil"
    DISCRETE_INPUT = "discrete_input"


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
    description: str = ""

    def __post_init__(self) -> None:
        if self.address < 0:
            raise ValueError("register addresses cannot be negative")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("register minimum cannot exceed maximum")
            if not self.writable:
                raise ValueError("bounded register must be writable")


# Values and names below are taken from docs/ProtokolModbusRTU_AirPack4.pdf.
# The PDF labels firmware, temperatures, serial number, and airflow as R/-.
# The mode/control words are R/W and are the only write surface exposed by the
# first controller implementation.
REGISTERS: tuple[RegisterDefinition, ...] = (
    RegisterDefinition("firmware_major", 0, RegisterArea.INPUT, description="MM"),
    RegisterDefinition("firmware_minor", 1, RegisterArea.INPUT, description="mm"),
    RegisterDefinition("firmware_patch", 4, RegisterArea.INPUT, description="pp"),
    RegisterDefinition("outdoor_temperature", 16, RegisterArea.INPUT, "°C", 0.1),
    RegisterDefinition("supply_temperature", 17, RegisterArea.INPUT, "°C", 0.1),
    RegisterDefinition("extract_temperature", 18, RegisterArea.INPUT, "°C", 0.1),
    RegisterDefinition("fpx_temperature", 19, RegisterArea.INPUT, "°C", 0.1),
    RegisterDefinition("duct_supply_temperature", 20, RegisterArea.INPUT, "°C", 0.1),
    RegisterDefinition("gwc_temperature", 21, RegisterArea.INPUT, "°C", 0.1),
    RegisterDefinition("ambient_temperature", 22, RegisterArea.INPUT, "°C", 0.1),
    RegisterDefinition("serial_number_1", 24, RegisterArea.INPUT),
    RegisterDefinition("serial_number_2", 25, RegisterArea.INPUT),
    RegisterDefinition("serial_number_3", 26, RegisterArea.INPUT),
    RegisterDefinition("serial_number_4", 27, RegisterArea.INPUT),
    RegisterDefinition("serial_number_5", 28, RegisterArea.INPUT),
    RegisterDefinition("serial_number_6", 29, RegisterArea.INPUT),
    RegisterDefinition("supply_airflow", 256, RegisterArea.INPUT, "m³/h"),
    RegisterDefinition("extract_airflow", 257, RegisterArea.INPUT, "m³/h"),
    RegisterDefinition(
        "constant_flow_active", 271, RegisterArea.INPUT,
        description="Status aktywności systemu Constant Flow",
    ),
    RegisterDefinition(
        "supply_percentage", 272, RegisterArea.INPUT, "%",
        description="Aktualnie zadana intensywność wentylacji - nawiew",
    ),
    RegisterDefinition(
        "extract_percentage", 273, RegisterArea.INPUT, "%",
        description="Aktualnie zadana intensywność wentylacji - wywiew",
    ),
    RegisterDefinition(
        "supply_flowrate", 274, RegisterArea.INPUT, "m³/h",
        description="Zadany strumień przepływu - nawiew (wartość panelu Air++)",
    ),
    RegisterDefinition(
        "extract_flowrate", 275, RegisterArea.INPUT, "m³/h",
        description="Zadany strumień przepływu - wywiew (wartość panelu Air++)",
    ),
    RegisterDefinition(
        "fpx_system_active", 4192, RegisterArea.HOLDING,
        description="Flaga systemu przeciwzamrożeniowego FPX; nie oznacza stanu samej grzałki",
    ),
    RegisterDefinition(
        "fpx_stage", 4198, RegisterArea.HOLDING,
        description="0 OFF, 1 FPX1, 2 FPX2",
    ),
    RegisterDefinition(
        "mode", 4208, RegisterArea.HOLDING, writable=True, minimum=0, maximum=2,
        description="0 automatic, 1 manual, 2 temporary",
    ),
    RegisterDefinition(
        "season", 4209, RegisterArea.HOLDING, writable=True, minimum=0, maximum=1,
        description="0 summer, 1 winter",
    ),
    RegisterDefinition(
        "manual_fan_speed", 4210, RegisterArea.HOLDING, "%", writable=True, minimum=10, maximum=100,
    ),
    RegisterDefinition(
        "temporary_fan_speed",
        4211,
        RegisterArea.HOLDING,
        "%",
        writable=True,
        minimum=10,
        maximum=100,
        description="Intensywność wentylacji w trybie chwilowym",
    ),
    RegisterDefinition(
        "special_mode", 4224, RegisterArea.HOLDING, writable=True, minimum=0, maximum=11,
        description="0 none, 2 fireplace, 3/4/7/8/9 airing, 10 open windows, 11 empty house",
    ),
    RegisterDefinition(
        "comfort_mode_panel", 4304, RegisterArea.HOLDING, writable=True, minimum=0, maximum=1,
        description="0 eco, 1 comfort",
    ),
    RegisterDefinition(
        "bypass_off", 4320, RegisterArea.HOLDING, writable=True, minimum=0, maximum=1,
        description="0 active, 1 inactive",
    ),
    RegisterDefinition("bypass_mode", 4330, RegisterArea.HOLDING),
    RegisterDefinition(
        "on_off_panel_mode", 4387, RegisterArea.HOLDING, writable=True, minimum=0, maximum=1,
        description="0 off, 1 on",
    ),
    RegisterDefinition(
        "temporary_activation_mode",
        4400,
        RegisterArea.HOLDING,
        writable=True,
        minimum=0,
        maximum=2,
        description="cfgMode1; first word of the atomic temporary-mode activation block",
    ),
    RegisterDefinition(
        "temporary_activation_speed",
        4401,
        RegisterArea.HOLDING,
        "%",
        writable=True,
        minimum=10,
        maximum=100,
        description="temporary airflow used in the atomic activation block",
    ),
    RegisterDefinition(
        "temporary_activation_flag",
        4402,
        RegisterArea.HOLDING,
        writable=True,
        minimum=0,
        maximum=1,
        description="airflowRateChangeFlag; write 1 with mode and speed in one operation",
    ),
    RegisterDefinition(
        "erv_post_heater_active", 4704, RegisterArea.HOLDING,
        description="Status wbudowanej nagrzewnicy wtórnej ERV: 0 inactive, 1 active",
    ),
    RegisterDefinition(
        "erv_post_heater_mode", 4711, RegisterArea.HOLDING,
        description="Konfiguracja wbudowanej nagrzewnicy wtórnej ERV: 0 off, 1 mode 1, 2 mode 2",
    ),
)


REGISTERS_BY_KEY = {register.key: register for register in REGISTERS}
