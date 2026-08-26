from thessla_green.domain.models import DeviceIdentity, TransportEndpoint, TransportKind
from thessla_green.registers import REGISTERS


def test_register_keys_are_unique() -> None:
    keys = [register.key for register in REGISTERS]
    assert len(keys) == len(set(keys))


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
