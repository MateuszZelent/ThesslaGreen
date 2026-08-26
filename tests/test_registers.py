import pytest

from thessla_green.domain.models import DeviceIdentity, TransportEndpoint, TransportKind
from thessla_green.protocol.codec import (
    decode_airflow,
    decode_airpack_temperature,
    decode_serial_number,
)
from thessla_green.registers import REGISTERS


def test_register_keys_are_unique() -> None:
    keys = [register.key for register in REGISTERS]
    assert len(keys) == len(set(keys))


def test_pdf_panel_flowrate_registers_are_mapped_separately_from_cf_measurements() -> None:
    by_key = {register.key: register for register in REGISTERS}

    assert by_key["supply_airflow"].address == 256
    assert by_key["extract_airflow"].address == 257
    assert by_key["constant_flow_active"].address == 271
    assert by_key["supply_flowrate"].address == 274
    assert by_key["extract_flowrate"].address == 275


def test_pdf_builtin_heater_diagnostics_are_read_only_and_mapped() -> None:
    by_key = {register.key: register for register in REGISTERS}

    assert by_key["fpx_system_active"].address == 4192
    assert by_key["fpx_stage"].address == 4198
    assert by_key["erv_post_heater_active"].address == 4704
    assert by_key["erv_post_heater_mode"].address == 4711
    assert all(
        not by_key[key].writable
        for key in (
            "fpx_system_active",
            "fpx_stage",
            "erv_post_heater_active",
            "erv_post_heater_mode",
        )
    )


def test_writable_registers_with_bounds_have_valid_ranges() -> None:
    for register in REGISTERS:
        if register.minimum is not None and register.maximum is not None:
            assert register.writable
            assert register.minimum <= register.maximum


def test_fallback_identity_is_safe_for_urls_and_entity_ids() -> None:
    identity = DeviceIdentity(
        model="AirPack4",
        unit_id=10,
        endpoint=TransportEndpoint(TransportKind.SERIAL, "/dev/ttyUSB0"),
    )

    assert identity.stable_id == "airpack4-serial--dev-ttyUSB0-10"
    assert "/" not in identity.stable_id


def test_pdf_serial_codec_preserves_the_legacy_stable_id() -> None:
    serial = decode_serial_number((0x7E, 0xDF, 0xC3, 0x1B, 0, 0))
    identity = DeviceIdentity(model="AirPack4", unit_id=10, serial_number=serial)

    assert serial == "7edf c31b 0000"
    assert identity.stable_id == "airpack4-007e-00df-00c3-001b-0000-0000-10"


def test_pdf_sentinel_codecs_reject_false_measurements() -> None:
    assert decode_airflow(0xFFFF) is None
    assert decode_airflow(0) == 0
    assert decode_airpack_temperature(0x8000) is None
    with pytest.raises(ValueError, match="-999..999"):
        decode_airpack_temperature(1000)


def test_temperature_codec_does_not_expose_binary_float_artifacts() -> None:
    assert decode_airpack_temperature(179) == 17.9
    assert str(decode_airpack_temperature(179)) == "17.9"
    assert decode_airpack_temperature(204) == 20.4
