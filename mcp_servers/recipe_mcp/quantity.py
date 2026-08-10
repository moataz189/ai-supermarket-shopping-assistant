"""Recipe-mcp's own "is this metric measure precise enough to use directly" check.
Spoonacular's `extendedIngredients[].measures.metric` is *usually* a real weight/volume
(e.g. "222 g"), but for some ingredients it's still a count or size descriptor Spoonacular
couldn't convert (e.g. "1 medium" onion, "4 servings" of a compound ingredient) — this is
what decides whether that measure can be used directly or the ingredientWidget endpoint
(which uses Spoonacular's ingredient-density database) needs to be consulted instead. Kept
separate from mcp_servers/retailer_cart_mcp/quantity.py's own unit sets: that module
decides how to convert an already-normalized amount into a specific retailer's selling
method; this one only judges Spoonacular's own metric measure, before that.
"""

_PRECISE_METRIC_UNITS = {
    "g", "gram", "grams",
    "kg", "kilogram", "kilograms",
    "ml", "milliliter", "milliliters", "millilitre", "millilitres",
    "l", "liter", "liters", "litre", "litres",
}


def is_precise_metric_unit(unit: str | None) -> bool:
    """True only for a real, deterministic metric weight/volume unit. False for
    anything else — a count, a size descriptor ("medium", "large"), "servings", a
    non-metric measure, or no measure at all (None/empty)."""
    if not unit:
        return False
    return unit.strip().lower() in _PRECISE_METRIC_UNITS
