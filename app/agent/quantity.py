"""Agent-local quantity helper for the comparison view (before a retailer is ever
chosen). Deliberately independent of mcp_servers/retailer_cart_mcp/quantity.py's own
packages_needed: app/ and mcp_servers/ are separate deployable services that only ever
talk to each other over the MCP protocol (see app/agent/mcp_clients.py), never via a
direct Python import, so this small amount of weight/volume-to-whole-package math is
intentionally duplicated here rather than imported across that boundary.

Real user report this fixes: a recipe needing 1000 g of pasta (matched to a 500 g
package) showed "× 1000 g" at a single package's price (₪7.90) in the comparison view,
even after the Retailer-Cart MCP was already correctly buying 2 packages (₪15.80) once
a retailer was chosen — the comparison view must show the same realistic estimate
up front, not just after the fact.
"""

import math

_WEIGHT_TO_KG = {
    "g": 0.001,
    "gram": 0.001,
    "grams": 0.001,
    "kg": 1.0,
    "kilogram": 1.0,
    "kilograms": 1.0,
}

_VOLUME_TO_L = {
    "ml": 0.001,
    "milliliter": 0.001,
    "milliliters": 0.001,
    "millilitre": 0.001,
    "millilitres": 0.001,
    "l": 1.0,
    "liter": 1.0,
    "liters": 1.0,
    "litre": 1.0,
    "litres": 1.0,
}


def _normalize(quantity: float, unit: str, table: dict[str, float]) -> float | None:
    factor = table.get(unit.strip().lower())
    return quantity * factor if factor is not None else None


def estimated_package_count(
    requested_quantity: float, requested_unit: str, package_size: float, package_unit: str
) -> int | None:
    """Best-effort "how many whole packages will this likely need" estimate for the
    comparison view — mirrors mcp_servers/retailer_cart_mcp/quantity.py's
    packages_needed (never rounds down, at least 1 package). Returns None when the two
    amounts aren't the same kind of quantity (a weight request against a package with
    no known weight/volume, a volume request against a weight-only package, etc.) — the
    comparison view falls back to showing the recipe's raw requested amount unchanged
    in that case, exactly as before this estimate existed."""
    requested_kg = _normalize(requested_quantity, requested_unit, _WEIGHT_TO_KG)
    package_kg = _normalize(package_size, package_unit, _WEIGHT_TO_KG)
    if requested_kg is not None and package_kg is not None and package_kg > 0:
        return max(1, math.ceil(round(requested_kg / package_kg, 9)))

    requested_l = _normalize(requested_quantity, requested_unit, _VOLUME_TO_L)
    package_l = _normalize(package_size, package_unit, _VOLUME_TO_L)
    if requested_l is not None and package_l is not None and package_l > 0:
        return max(1, math.ceil(round(requested_l / package_l, 9)))

    return None


# Mirrors mcp_servers/retailer_cart_mcp/quantity.py's is_count_unit/
# estimate_weight_kg_for_count exactly (same constant, so the comparison view's price
# and the real cart-add agree) -- see that module's docstring for why this is
# intentionally duplicated rather than imported.
_VOLUME_UNITS = {
    "ml", "milliliter", "milliliters", "millilitre", "millilitres",
    "l", "liter", "liters", "litre", "litres",
    "cup", "cups",
    "tbsp", "tablespoon", "tablespoons",
    "tsp", "teaspoon", "teaspoons",
    "fl oz", "fluid ounce", "fluid ounces",
    "pint", "pints", "quart", "quarts", "gallon", "gallons",
}

DEFAULT_KG_PER_COUNT_UNIT = 0.5

# A recipe's count unit is either "N whole discrete items" (a bare "unit", "large",
# "medium" -- an egg, an onion, a tomato) or "N small portions of a larger item" (a
# clove of a garlic bulb, a sprig of an herb, a pinch of a spice, a slice/stalk/wedge of
# something) -- two categories with wildly different real-world weights, so the same
# flat 0.5 kg/unit estimate that's a reasonable guess for the first is off by one to two
# orders of magnitude for the second (real user report, 2026-08-14: "4 clove" of garlic
# priced as 2 kg -- ₪272.50 for garlic -- against a product sold by weight). Deliberately
# a second flat constant, not a per-ingredient lookup table this project has no reliable
# source for (same reasoning DEFAULT_KG_PER_COUNT_UNIT itself already applies to the
# "whole item" category) -- classified by the unit word itself, general cooking
# vocabulary, never by which ingredient it's attached to.
_SMALL_PORTION_UNITS = {
    "clove", "cloves", "sprig", "sprigs", "pinch", "pinches", "dash", "dashes",
    "slice", "slices", "stalk", "stalks", "sliver", "slivers", "knob", "knobs",
    "wedge", "wedges", "leaf", "leaves",
}
DEFAULT_KG_PER_SMALL_PORTION_UNIT = 0.02


def is_count_unit(unit: str) -> bool:
    """True for anything that reads as "N discrete items" rather than a weight or a
    volume -- see mcp_servers/retailer_cart_mcp/quantity.py's identical function for the
    full rationale (classifies by elimination, not an allowlist)."""
    normalized = unit.strip().lower()
    return normalized not in _WEIGHT_TO_KG and normalized not in _VOLUME_UNITS


def estimate_weight_kg_for_count(quantity: float, unit: str) -> float:
    """Best-effort fallback weight (kg) for a bare unit count against a product sold by
    weight (e.g. "1 onion" against loose onions priced per kg), for the comparison
    view's price estimate -- real user report: this showed the full per-kg price for an
    item that the real cart-add (see mcp_servers/retailer_cart_mcp/quantity.py's
    identical estimate) actually only adds ~0.5 kg of. Deliberately coarse, matching
    that module's constant exactly rather than drifting from it. `unit` picks between
    the "whole item" and "small portion" estimate (see _SMALL_PORTION_UNITS) -- callers
    must only use this for a count unit (is_count_unit)."""
    is_small_portion = unit.strip().lower() in _SMALL_PORTION_UNITS
    per_unit = DEFAULT_KG_PER_SMALL_PORTION_UNIT if is_small_portion else DEFAULT_KG_PER_COUNT_UNIT
    return round(quantity * per_unit, 3)
