"""Data-driven fallback quantities for ingredients where Spoonacular's own data (both
extendedIngredients.measures.metric and ingredientWidget.json) resolves to a
non-actionable placeholder unit -- "serving"/"servings", or an empty unit -- rather than
a real, buyable quantity. Confirmed live against a real recipe (Spoonacular id 652061,
"Miso Cream Pasta"): several ingredients genuinely have no better data anywhere, and
Spoonacular's own "amount" there is just the recipe's serving count, not a real
ingredient quantity — buying that many units would be wrong (e.g. "4 servings" of onion
is not 4 onions, and "36 servings" of shiso leaves is not 36 leaves).

Two data-driven tables, checked in order by `default_quantity_for`, plus a universal
fallback:
- PER_SERVING_DEFAULTS: a real per-serving weight/volume, scaled by the *requested*
  servings (not the recipe's own base serving count — see server.py's ratio, which this
  is deliberately independent of).
- WEIGHT_DEFAULTS: produce known to be weighed rather than counted, with no deterministic
  per-serving amount, given a flat, reasonable default request — the retailer's own
  increment rounding (see mcp_servers/retailer_cart_mcp/quantity.py) still applies on top
  of this later, once a specific retailer's real supported increment is known.
- Anything else — including an ingredient with no entry in either table at all, e.g.
  "shiso leaves" — matches how most grocery items are actually sold: a single
  unit/pack, never the raw (meaningless) servings count.

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
    # Unlike a weight/volume ingredient, this is a real fractional *count* per serving
    # (a quarter onion) -- the same table, a count unit instead of "g"/"ml", scaled by
    # target_servings exactly like the others (real user report: 40 servings still
    # bought a flat "1 unit" of onion before this entry existed).
    "onion": (0.25, "unit"),
    # Real user report (2026-08-14): the flat "1 unit" fallback (see
    # default_quantity_for below) reached a fixed 100 g spice package, and
    # build_retailer_cart.py's own "bare count against a weight-sold product"
    # estimate (0.5 kg/unit -- correct for loose produce sold by weight) fired on it
    # too, pricing "1 unit" of ground pepper as if it meant 0.5 kg of it (~₪63 instead
    # of one ₪12.70 packet). A real per-serving gram amount here sidesteps that
    # entirely -- ~0.5 g/serving (a pinch) is a realistic seasoning amount.
    "ground pepper": (0.5, "g"),
    "pepper": (0.5, "g"),
}

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


def default_quantity_for(name: str, target_servings: int) -> tuple[float, str]:
    """Returns (amount, unit) for a data-driven fallback when an ingredient's resolved
    unit is non-actionable. Always returns something usable — a real per-serving
    weight/volume when known, a flat weight default for known weight-sold produce, or,
    for anything else (sold by unit, or simply not in either table), a single unit —
    never the raw, meaningless servings count."""
    key = name.strip().lower()
    if key in PER_SERVING_DEFAULTS:
        amount_per_serving, unit = PER_SERVING_DEFAULTS[key]
        return amount_per_serving * target_servings, unit
    if key in WEIGHT_DEFAULTS:
        return WEIGHT_DEFAULTS[key], "kg"
    return 1.0, "unit"
