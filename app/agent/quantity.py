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
