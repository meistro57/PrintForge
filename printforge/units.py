"""Exact physical lengths.

Lengths are stored as exact rational inches (:class:`fractions.Fraction`), so
mixing millimetres, points and inches never accumulates floating-point drift.
Values are only rounded when serialized (:meth:`Length.to_str`) or handed to a
renderer (:meth:`Length.css`).

Accepted input syntax: ``"6in"``, ``"0.125 in"``, ``"3.2mm"``, ``"0.32cm"``,
``"10.5pt"``. Bare numbers are rejected: units must be explicit.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from functools import total_ordering

# Exact conversion factors to inches.
UNITS: dict[str, Fraction] = {
    "in": Fraction(1),
    "mm": Fraction(10, 254),
    "cm": Fraction(100, 254),
    "pt": Fraction(1, 72),
}
_PATTERN = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(in|mm|cm|pt)\s*$")
SERIAL_PLACES = 6  # decimal places kept when serializing


class UnitError(ValueError):
    """Raised for unparsable or unit-less length values."""


@total_ordering
class Length:
    """An exact length. ``unit`` is only the preferred *display* unit; equality,
    ordering and hashing depend on the physical size alone."""

    __slots__ = ("_inches", "unit")

    def __init__(self, inches: Fraction | int | str | Decimal, unit: str = "in") -> None:
        self._inches = Fraction(inches)
        if unit not in UNITS:
            raise UnitError(f"unknown unit {unit!r}")
        self.unit = unit

    # ---------------------------------------------------------------- creation
    @classmethod
    def parse(cls, value: object) -> Length:
        if isinstance(value, Length):
            return value
        if isinstance(value, bool) or not isinstance(value, str):
            raise UnitError(
                f"expected a length with explicit units such as '0.5in' or '12.7mm', got {value!r}"
            )
        match = _PATTERN.match(value)
        if not match:
            raise UnitError(f"invalid length {value!r}; use a number followed by in, mm, cm or pt")
        number, unit = match.groups()
        return cls(Fraction(Decimal(number)) * UNITS[unit], unit)

    @classmethod
    def inches(cls, value: str | int) -> Length:
        return cls(Fraction(Decimal(str(value))))

    @classmethod
    def mm(cls, value: str | int) -> Length:
        return cls(Fraction(Decimal(str(value))) * UNITS["mm"], "mm")

    @classmethod
    def pt(cls, value: str | int) -> Length:
        return cls(Fraction(Decimal(str(value))) * UNITS["pt"], "pt")

    # ---------------------------------------------------------------- access
    @property
    def exact_inches(self) -> Fraction:
        return self._inches

    def to(self, unit: str, places: int = SERIAL_PLACES) -> Decimal:
        """Value in ``unit``, rounded half-even to ``places`` decimals."""
        value = self._inches / UNITS[unit]
        quantum = Decimal(1).scaleb(-places)
        return (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
            quantum, rounding=ROUND_HALF_EVEN
        )

    def to_str(self, unit: str | None = None, places: int = SERIAL_PLACES) -> str:
        """Normalized serialization in ``unit`` (default: the display unit), e.g.
        ``"0.125in"`` or ``"10.5pt"``; trailing zeros dropped."""
        unit = unit or self.unit
        text = format(self.to(unit, places).normalize(), "f")
        if text in ("-0", "0"):
            text = "0"
        return f"{text}{unit}"

    def css(self) -> str:
        """CSS length in inches with 4 decimal places (sub-micrometre precision)."""
        return self.to_str("in", 4)

    # ---------------------------------------------------------------- arithmetic
    def __add__(self, other: Length) -> Length:
        return Length(self._inches + other._inches)

    def __sub__(self, other: Length) -> Length:
        return Length(self._inches - other._inches)

    def __mul__(self, factor: int | Fraction | Decimal) -> Length:
        return Length(self._inches * Fraction(factor), self.unit)

    __rmul__ = __mul__

    def __truediv__(self, divisor: int | Fraction) -> Length:
        return Length(self._inches / Fraction(divisor), self.unit)

    def __neg__(self) -> Length:
        return Length(-self._inches, self.unit)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Length) and self._inches == other._inches

    def __lt__(self, other: Length) -> bool:
        return self._inches < other._inches

    def __hash__(self) -> int:
        return hash(self._inches)

    def __repr__(self) -> str:
        return f"Length({self.to_str()!r})"

    def __str__(self) -> str:
        return self.to_str()


ZERO = Length(0)
