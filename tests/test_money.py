import pytest

from mitosis.money import format_minor_units, parse_minor_units


def test_parse_basic_usd():
    assert parse_minor_units("5.00", "USD_SIM") == 500
    assert parse_minor_units("0.01", "USD_REAL") == 1
    assert parse_minor_units("1234.56", "USD_SIM") == 123456


def test_parse_integer_string():
    assert parse_minor_units("5", "USD_SIM") == 500


def test_parse_resource_book_has_no_fractional_units():
    assert parse_minor_units("42", "RESOURCE") == 42
    with pytest.raises(ValueError):
        parse_minor_units("42.5", "RESOURCE")


def test_parse_rejects_excess_precision():
    with pytest.raises(ValueError):
        parse_minor_units("5.001", "USD_SIM")


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_minor_units("not-a-number", "USD_SIM")


def test_parse_rejects_unknown_book():
    with pytest.raises(ValueError):
        parse_minor_units("5.00", "USD_FAKE")


def test_format_round_trips():
    assert format_minor_units(500, "USD_SIM") == "5.00"
    assert format_minor_units(1, "USD_REAL") == "0.01"
    assert format_minor_units(42, "RESOURCE") == "42"


def test_negative_amounts_round_trip():
    assert parse_minor_units("-5.00", "USD_SIM") == -500
    assert format_minor_units(-500, "USD_SIM") == "-5.00"
