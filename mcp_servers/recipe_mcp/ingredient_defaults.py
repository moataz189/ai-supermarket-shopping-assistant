"""Data-driven fallback quantities for ingredients where Spoonacular's own data (both
extendedIngredients.measures.metric and ingredientWidget.json) resolves to a
non-actionable placeholder unit -- "serving"/"servings", or an empty unit -- rather than
a real, buyable quantity. Confirmed live against a real recipe (Spoonacular id 652061,
"Miso Cream Pasta"): several ingredients genuinely have no better data anywhere, and
Spoonacular's own "amount" there is just the recipe's serving count, not a real
ingredient quantity — buying that many units would be wrong (e.g. "4 servings" of onion
is not 4 onions).

Three independent tables, checked in order by `default_quantity_for`:
- PER_SERVING_DEFAULTS: a real per-serving weight/volume, scaled by the *requested*
  servings (not the recipe's own base serving count — see server.py's ratio, which this
  is deliberately independent of).
- UNIT_DEFAULTS: whole produce normally bought one at a time regardless of how many
  servings the recipe calls for.
- WEIGHT_DEFAULTS: weighed produce with no deterministic per-serving amount, given a
  flat, reasonable default request — the retailer's own increment rounding (see
  mcp_servers/retailer_cart_mcp/quantity.py) still applies on top of this later, once a
  specific retailer's real supported increment is known.

Deliberately small and easy to extend: add an entry to whichever table fits, nothing
else in the codebase needs to change.
"""

_NON_ACTIONABLE_UNITS = {"serving", "servings", ""}

PER_SERVING_DEFAULTS: dict[str, tuple[float, str]] = {
    "pasta": (125.0, "g"),
    "rice": (75.0, "g"),
    "olive oil": (15.0, "ml"),
    "parmesan": (10.0, "g"),
    "butter": (15.0, "g"),
}

UNIT_DEFAULTS: set[str] = {"onion", "melon", "cabbage"}

WEIGHT_DEFAULTS: dict[str, float] = {  # ingredient name -> default kg
    "tomatoes": 0.5,
    "potatoes": 0.5,
    "apples": 0.5,
}


def is_non_actionable_unit(unit: str | None) -> bool:
    """True for a unit that isn't a real, buyable quantity at all -- a bare "serving"/
    "servings" count, or no unit. False for anything else (a real weight/volume unit, a
    count unit like "clove", or a non-metric-but-still-meaningful unit like "Tbsp")."""
    if unit is None:
        return True
    return unit.strip().lower() in _NON_ACTIONABLE_UNITS


def default_quantity_for(name: str, target_servings: int) -> tuple[float, str] | None:
    """Returns (amount, unit) for a data-driven fallback when an ingredient's resolved
    unit is non-actionable. None if this ingredient isn't in any of the default tables —
    callers should fall back further (e.g. to whatever raw value Spoonacular gave) in
    that case."""
    key = name.strip().lower()
    if key in PER_SERVING_DEFAULTS:
        amount_per_serving, unit = PER_SERVING_DEFAULTS[key]
        return amount_per_serving * target_servings, unit
    if key in UNIT_DEFAULTS:
        return 1.0, "unit"
    if key in WEIGHT_DEFAULTS:
        return WEIGHT_DEFAULTS[key], "kg"
    return None
