from thessla_green.registers import REGISTERS


def test_register_keys_are_unique() -> None:
    keys = [register.key for register in REGISTERS]
    assert len(keys) == len(set(keys))


def test_writable_registers_with_bounds_have_valid_ranges() -> None:
    for register in REGISTERS:
        if register.minimum is not None and register.maximum is not None:
            assert register.writable
            assert register.minimum <= register.maximum

