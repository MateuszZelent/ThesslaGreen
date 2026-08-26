"""Temperature and airflow sensors from the coordinated gateway snapshot."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant

from .entity import ThesslaGreenEntity


@dataclass(frozen=True, slots=True)
class SensorSpec:
    key: str
    name: str
    unit: str
    device_class: SensorDeviceClass | None = None


SENSORS = (
    SensorSpec(
        "outdoor_temperature",
        "Temperatura zewnętrzna",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
    ),
    SensorSpec(
        "supply_temperature",
        "Temperatura nawiewu",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
    ),
    SensorSpec(
        "extract_temperature",
        "Temperatura wywiewu",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
    ),
    SensorSpec(
        "fpx_temperature",
        "Temperatura FPX",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
    ),
    SensorSpec(
        "duct_supply_temperature",
        "Temperatura kanału",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
    ),
    SensorSpec(
        "gwc_temperature",
        "Temperatura GWC",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
    ),
    SensorSpec(
        "ambient_temperature",
        "Temperatura otoczenia",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
    ),
    SensorSpec("supply_flowrate", "Zadany strumień nawiewu", "m³/h"),
    SensorSpec("extract_flowrate", "Zadany strumień wywiewu", "m³/h"),
    SensorSpec("supply_airflow", "Chwilowy pomiar CF nawiewu", "m³/h"),
    SensorSpec("extract_airflow", "Chwilowy pomiar CF wywiewu", "m³/h"),
    SensorSpec("supply_percentage", "Zadana intensywność nawiewu", "%"),
    SensorSpec("extract_percentage", "Zadana intensywność wywiewu", "%"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            *(ThesslaGreenSensor(coordinator, spec) for spec in SENSORS),
            ThesslaGreenLastCommandSensor(coordinator),
        ]
    )


class ThesslaGreenSensor(ThesslaGreenEntity, SensorEntity):
    """One read-only sensor backed by a key in ``state.values``."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, spec: SensorSpec) -> None:
        super().__init__(coordinator, spec.key)
        self.spec = spec
        self._attr_name = spec.name
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_device_class = spec.device_class

    @property
    def native_value(self) -> object:
        return self.values.get(self.spec.key)


class ThesslaGreenLastCommandSensor(ThesslaGreenEntity, SensorEntity):
    """Show the last command that completed a register read-back."""

    _attr_name = "Ostatnie potwierdzone polecenie"
    _attr_icon = "mdi:check-network"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "last_command")

    @property
    def native_value(self) -> str | None:
        command = self.coordinator.last_command
        if not isinstance(command, Mapping):
            return None
        value = command.get("command")
        return str(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        command = self.coordinator.last_command
        return dict(command) if isinstance(command, Mapping) else {}
