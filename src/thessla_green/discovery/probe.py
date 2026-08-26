"""Read-only AirPack fingerprint probe."""

from __future__ import annotations

from thessla_green.domain.models import (
    Capabilities,
    DeviceIdentity,
    DiscoveryResult,
    ProbeStatus,
    TransportEndpoint,
)
from thessla_green.protocol.codec import (
    decode_airpack_temperature,
    decode_firmware_version,
    decode_serial_number,
)
from thessla_green.protocol.profile import AIRPACK4_PROFILE, AirPackRegisterProfile
from thessla_green.protocol.transport import ModbusTransport, ReadResponseError


class AirPackProbe:
    """Identify an AirPack using only input-register reads.

    The three requests stay below the vendor's maximum of 16 registers per
    operation and return raw evidence for diagnostics/audit.
    """

    def __init__(self, profile: AirPackRegisterProfile = AIRPACK4_PROFILE) -> None:
        self.profile = profile

    async def run(
        self,
        transport: ModbusTransport,
        endpoint: TransportEndpoint,
        unit_id: int,
    ) -> DiscoveryResult:
        evidence: dict[str, object] = {
            "profile": self.profile.model_name,
            "read_only": True,
            "function_codes": [4],
        }
        try:
            firmware_block = await transport.read_input_registers(0, 5, unit_id)
            temperature_block = await transport.read_input_registers(
                self.profile.temperature_address, self.profile.temperature_count, unit_id
            )
            serial_block = await transport.read_input_registers(
                self.profile.serial_address, self.profile.serial_count, unit_id
            )
        except (ReadResponseError, OSError, TimeoutError) as exc:
            return DiscoveryResult(
                endpoint=endpoint,
                unit_id=unit_id,
                status=ProbeStatus.NO_RESPONSE,
                evidence=evidence,
                error=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive boundary for hardware drivers
            return DiscoveryResult(
                endpoint=endpoint,
                unit_id=unit_id,
                status=ProbeStatus.ERROR,
                evidence=evidence,
                error=f"unexpected probe error: {exc}",
            )

        try:
            if len(firmware_block) != 5:
                raise ReadResponseError("firmware response length is not five registers")
            if len(temperature_block) != self.profile.temperature_count:
                raise ReadResponseError("temperature response length is invalid")
            if len(serial_block) != self.profile.serial_count:
                raise ReadResponseError("serial response length is invalid")

            firmware = decode_firmware_version(
                (firmware_block[0], firmware_block[1], firmware_block[4])
            )
            serial_number = decode_serial_number(serial_block)
            temperatures = {
                "outdoor_temperature": decode_airpack_temperature(temperature_block[0]),
                "supply_temperature": decode_airpack_temperature(temperature_block[1]),
                "extract_temperature": decode_airpack_temperature(temperature_block[2]),
                "fpx_temperature": decode_airpack_temperature(temperature_block[3]),
                "duct_supply_temperature": decode_airpack_temperature(temperature_block[4]),
                "gwc_temperature": decode_airpack_temperature(temperature_block[5]),
                "ambient_temperature": decode_airpack_temperature(temperature_block[6]),
            }
            if not 0 <= firmware_block[2] <= 6:
                raise ValueError("day_of_week register is outside the documented range 0..6")
            if not 0 <= firmware_block[3] <= 3:
                raise ValueError("period register is outside the documented range 0..3")
        except (ValueError, IndexError, ReadResponseError) as exc:
            evidence.update(
                firmware_registers=list(firmware_block),
                temperature_registers=list(temperature_block),
                serial_registers=list(serial_block),
            )
            return DiscoveryResult(
                endpoint=endpoint,
                unit_id=unit_id,
                status=ProbeStatus.UNKNOWN_MODBUS_DEVICE,
                evidence=evidence,
                error=f"valid Modbus response but invalid AirPack fingerprint: {exc}",
            )

        evidence.update(
            firmware_registers=list(firmware_block),
            temperature_registers=list(temperature_block),
            serial_registers=list(serial_block),
            firmware=".".join(str(part) for part in firmware),
            serial_number=serial_number or None,
            temperatures=temperatures,
        )
        known_version = (
            (firmware[0] in {3, 4} or 90 <= firmware[0] <= 99)
            and 0 <= firmware[1] <= 99
            and 0 <= firmware[2] <= 99
        )
        if not known_version or not serial_number:
            return DiscoveryResult(
                endpoint=endpoint,
                unit_id=unit_id,
                status=ProbeStatus.UNKNOWN_MODBUS_DEVICE,
                evidence=evidence,
                error="response is Modbus-compatible but not a confirmed AirPack4 fingerprint",
            )

        identity = DeviceIdentity(
            model=self.profile.model_name,
            unit_id=unit_id,
            firmware=firmware,
            serial_number=serial_number,
            endpoint=endpoint,
        )
        return DiscoveryResult(
            endpoint=endpoint,
            unit_id=unit_id,
            status=ProbeStatus.AIRPACK,
            identity=identity,
            evidence=evidence,
        )

    @staticmethod
    def capabilities(result: DiscoveryResult) -> Capabilities:
        """Return the conservative initial feature set for a confirmed result."""

        if not result.is_selectable:
            return Capabilities()
        return Capabilities(
            features=frozenset(
                {
                    "temperatures",
                    "airflow",
                    "mode",
                    "season",
                    "manual_fan_speed",
                    "temporary_fan_speed",
                    "special_mode",
                    "comfort_mode",
                    "bypass_off",
                    "on_off",
                }
            ),
            min_fan_percentage=10,
            max_fan_percentage=100,
        )
