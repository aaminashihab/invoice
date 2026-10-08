"""Unit registry, canonical normalization, and dimensional conversion rules.

Business Rules:
- Same canonical unit -> factor 1.
- Same dimension (kg <-> t) -> built-in global conversion.
- Cross-dimension (bag <-> t, m3 <-> t, load <-> m3) -> requires an explicit CONFIRMED material-scoped conversion rule.
- Never compare incompatible units without a confirmed conversion rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class UnitDimension(str, Enum):
    VOLUME = "VOLUME"
    MASS = "MASS"
    COUNT = "COUNT"
    LENGTH = "LENGTH"
    AREA = "AREA"
    PACKAGE = "PACKAGE"
    TRIP = "TRIP"


@dataclass(frozen=True)
class CanonicalUnit:
    code: str
    dimension: UnitDimension
    aliases: tuple[str, ...]


CANONICAL_UNITS: dict[str, CanonicalUnit] = {
    "m3": CanonicalUnit("m3", UnitDimension.VOLUME, ("cum", "m³", "cbm", "cu.m", "cubic meter", "cubic metres")),
    "l": CanonicalUnit("l", UnitDimension.VOLUME, ("liter", "litre", "ltr")),
    "t": CanonicalUnit("t", UnitDimension.MASS, ("mt", "tonne", "tonnes", "metric ton", "metric tonne")),
    "kg": CanonicalUnit("kg", UnitDimension.MASS, ("kgs", "kilogram", "kilograms")),
    "nos": CanonicalUnit("nos", UnitDimension.COUNT, ("pcs", "pieces", "units", "nr", "ea", "each")),
    "bag": CanonicalUnit("bag", UnitDimension.PACKAGE, ("bags", "bg")),
    "m": CanonicalUnit("m", UnitDimension.LENGTH, ("meter", "metre", "mtr", "linear meter")),
    "m2": CanonicalUnit("m2", UnitDimension.AREA, ("sqm", "m²", "sq.m", "square meter")),
    "load": CanonicalUnit("load", UnitDimension.TRIP, ("trip", "truck", "loads")),
}

# Lookup map normalized_alias -> canonical_code
_ALIAS_TO_CANONICAL: dict[str, str] = {}
for code, unit_def in CANONICAL_UNITS.items():
    _ALIAS_TO_CANONICAL[code.lower()] = code
    for alias in unit_def.aliases:
        _ALIAS_TO_CANONICAL[alias.lower().strip()] = code

# Standard same-dimension conversions
# (from_unit, to_unit) -> factor such that qty_to = qty_from * factor
STANDARD_CONVERSIONS: dict[tuple[str, str], Decimal] = {
    ("t", "kg"): Decimal(1000),
    ("kg", "t"): Decimal("0.001"),
    ("m3", "l"): Decimal(1000),
    ("l", "m3"): Decimal("0.001"),
}


def normalize_unit(unit_str: str | None) -> str | None:
    """Normalize input unit string to canonical unit code. Returns None if unknown/bare 'ton'."""
    if not unit_str:
        return None
    cleaned = unit_str.strip().lower()
    # Ambiguity A8 / assumption 5: bare "ton" is untrusted until confirmed
    if cleaned in ("ton", "tons"):
        return None
    return _ALIAS_TO_CANONICAL.get(cleaned)


@dataclass(frozen=True)
class ConversionResult:
    is_compatible: bool
    factor: Decimal = Decimal(1)
    rule_source: str = "SAME_UNIT"
    error_message: str | None = None


def resolve_unit_conversion(
    from_unit: str,
    to_unit: str,
    material_code: str | None = None,
    material_conversions: dict[tuple[str, str, str], Decimal] | None = None,
) -> ConversionResult:
    """Resolve conversion factor from from_unit to to_unit.

    Returns ConversionResult with is_compatible=False if incompatible.
    """
    u_from = normalize_unit(from_unit)
    u_to = normalize_unit(to_unit)

    if not u_from or not u_to:
        return ConversionResult(
            is_compatible=False,
            error_message=f"One or both units ('{from_unit}', '{to_unit}') are unrecognized or ambiguous.",
        )

    if u_from == u_to:
        return ConversionResult(is_compatible=True, factor=Decimal(1), rule_source="SAME_UNIT")

    # Check same-dimension standard conversions
    pair = (u_from, u_to)
    if pair in STANDARD_CONVERSIONS:
        return ConversionResult(
            is_compatible=True,
            factor=STANDARD_CONVERSIONS[pair],
            rule_source="STANDARD_SAME_DIMENSION",
        )

    # Check confirmed material-specific conversion rules
    if material_code and material_conversions:
        mat_key = (material_code.upper(), u_from, u_to)
        if mat_key in material_conversions:
            return ConversionResult(
                is_compatible=True,
                factor=material_conversions[mat_key],
                rule_source="CONFIRMED_MATERIAL_RULE",
            )

    dim_from = CANONICAL_UNITS[u_from].dimension
    dim_to = CANONICAL_UNITS[u_to].dimension

    return ConversionResult(
        is_compatible=False,
        error_message=(
            f"Cross-dimensional unit conversion from '{u_from}' ({dim_from.value}) to "
            f"'{u_to}' ({dim_to.value}) requires a confirmed material-specific conversion rule."
        ),
    )
