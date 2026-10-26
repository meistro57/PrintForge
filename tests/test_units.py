from decimal import Decimal
from fractions import Fraction

import pytest

from printforge.units import Length, UnitError


@pytest.mark.parametrize(
    ("text", "inches"),
    [
        ("6in", Fraction(6)),
        ("0.125 in", Fraction(1, 8)),
        ("25.4mm", Fraction(1)),
        ("2.54cm", Fraction(1)),
        ("72pt", Fraction(1)),
        ("10.5pt", Fraction(21, 144)),
        (".5in", Fraction(1, 2)),
    ],
)
def test_parse_exact(text, inches):
    assert Length.parse(text).exact_inches == inches


@pytest.mark.parametrize("bad", [6, 6.0, "6", "six in", "6 furlongs", None, True, "", "6in 2in"])
def test_parse_requires_explicit_units(bad):
    with pytest.raises(UnitError):
        Length.parse(bad)


def test_no_drift_over_repeated_conversion():
    total = Length(0)
    for _ in range(10_000):
        total = total + Length.parse("0.0572mm")  # KDP white-paper spine per page
    assert total == Length.parse("572mm")
    assert total.to("mm") == Decimal("572.000000")


def test_mixed_units_exact():
    assert Length.parse("0.125in") + Length.parse("3.175mm") == Length.parse("0.25in")
    assert Length.parse("1in") - Length.parse("72pt") == Length(0)


def test_serialization_keeps_display_unit_and_normalizes():
    assert Length.parse("10.50pt").to_str() == "10.5pt"
    assert Length.parse("3.2mm").to_str() == "3.2mm"
    assert Length.parse("3.2mm").to_str("in") == "0.125984in"
    assert Length.parse("6.000in").to_str() == "6in"
    assert Length.parse("0in").to_str() == "0in"
    assert Length.parse("1in").css() == "1in"
    assert Length.parse("1mm").css() == "0.0394in"


def test_equality_ignores_display_unit():
    assert Length.parse("25.4mm") == Length.parse("1in")
    assert hash(Length.parse("25.4mm")) == hash(Length.parse("1in"))
    assert Length.parse("1pt") < Length.parse("1mm") < Length.parse("1in")
