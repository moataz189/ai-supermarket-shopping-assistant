"""Retailer-agnostic quantity conversion helpers, shared by every adapter that needs to
turn a recipe's requested amount+unit (e.g. "400 g", "3 large") into an actual retailer
cart quantity (CP9 follow-up, 2026-08-08 — see docs/plan for the full bug writeup this
fixes: build_retailer_cart previously hardcoded qty=1 for every item regardless of what a
recipe actually asked for).

Nothing here talks to a browser or a specific site — these are pure functions, generic
across retailers and products by construction (classification is by unit string, not by
product name — "do not hardcode tomatoes"). Each adapter is still responsible for its own
site-specific mechanics (how to actually set a weight/count on the real page), but the
*decision* of what target to aim for, and whether a deterministic conversion exists at
all, lives here once instead of being duplicated (and potentially drifting) per adapter.
"""

import math
from dataclasses import dataclass

# Recognized weight units, normalized to a kg multiplier. Deliberately small and explicit
# — anything not listed here is NOT assumed to be a weight (see is_count_unit below),
# because guessing a unit's meaning wrong is worse than admitting we don't know it.
_WEIGHT_TO_KG = {
    "g": 0.001,
    "gram": 0.001,
    "grams": 0.001,
    "kg": 1.0,
    "kilogram": 1.0,
    "kilograms": 1.0,
}

# Recognized volume units. These are neither a weight NOR a plain count — converting a
# volume to a weight requires the ingredient's density, which this project has no
# deterministic source for, so they're tracked separately purely to be correctly
# *excluded* from "count-like" (see is_count_unit) rather than mis-treated as a unit count.
_VOLUME_UNITS = {
    "ml", "milliliter", "milliliters", "millilitre", "millilitres",
    "l", "liter", "liters", "litre", "litres",
    "cup", "cups",
    "tbsp", "tablespoon", "tablespoons",
    "tsp", "teaspoon", "teaspoons",
    "fl oz", "fluid ounce", "fluid ounces",
    "pint", "pints", "quart", "quarts", "gallon", "gallons",
}


def normalize_weight_to_kg(quantity: float, unit: str) -> float | None:
    """Returns `quantity` expressed in kg if `unit` is a recognized weight unit, else
    None. None is the honest answer for anything this can't deterministically convert —
    callers must not guess a fallback for it (e.g. a bare unit count has no defined
    weight without a per-product density/size the project doesn't have a source for)."""
    factor = _WEIGHT_TO_KG.get(unit.strip().lower())
    return round(quantity * factor, 6) if factor is not None else None


# Recognized volume units, normalized to a liter multiplier. Deliberately mirrors
# _WEIGHT_TO_KG's strictness (see normalize_weight_to_kg) -- only ml/l forms are
# deterministic; anything else (cup, tbsp, ...) has no fixed, ingredient-independent
# volume conversion and must not be guessed at here.
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


def normalize_volume_to_l(quantity: float, unit: str) -> float | None:
    """Returns `quantity` expressed in liters if `unit` is a recognized volume unit
    (ml/l forms only), else None — mirrors normalize_weight_to_kg's philosophy: an
    honest None for anything not deterministically convertible, never a guess."""
    factor = _VOLUME_TO_L.get(unit.strip().lower())
    return round(quantity * factor, 6) if factor is not None else None


def is_count_unit(unit: str) -> bool:
    """True for anything that reads as "N discrete items" rather than a weight or a
    volume. Deliberately classifies by *elimination* (not a recognized weight/volume
    unit) rather than an allowlist of count-unit strings: real Spoonacular data uses all
    sorts of whole-item descriptors for countable ingredients — e.g. eggs commonly come
    back with unit "large", not "unit" (confirmed against the fixture already used in
    tests/agent/test_graph_recipe_happy_path.py) — and an allowlist would silently miss
    those and misclassify them as "needs weight/volume conversion"."""
    normalized = unit.strip().lower()
    return normalized not in _WEIGHT_TO_KG and normalized not in _VOLUME_UNITS


def round_up_to_increment(requested_kg: float, increment_kg: float) -> float:
    """ceil(requested/increment) * increment — the smallest multiple of `increment_kg`
    that is >= `requested_kg`. Never rounds down, per product decision (a usable cart at
    slightly more than requested beats one silently short of what a recipe needs).

    Guards against float precision artifacts (e.g. 0.5/0.5 evaluating to a hair above
    1.0 and ceiling to a spurious extra increment) by rounding the division to 9 decimal
    places before taking the ceiling — grocery quantities never need finer precision than
    that, so this only ever cancels binary-float representation noise, never a real
    fractional difference.
    """
    steps = math.ceil(round(requested_kg / increment_kg, 9))
    return round(steps * increment_kg, 6)


def packages_needed(
    requested_quantity: float, requested_unit: str, package_size: float, package_unit: str
) -> int | None:
    """How many whole packages of `package_size` `package_unit` are needed to cover at
    least `requested_quantity` `requested_unit` (e.g. a recipe needing 1000 g of pasta,
    sold in 500 g packages, needs 2) — never rounds down, so the recipe is never left
    short. Returns None when the two amounts aren't the same kind of quantity (a weight
    request against a package with no known weight/volume, a volume request against a
    weight-only package, etc.) — callers must fall back to buying a single package
    rather than guessing a conversion in that case.
    """
    requested_kg = normalize_weight_to_kg(requested_quantity, requested_unit)
    package_kg = normalize_weight_to_kg(package_size, package_unit)
    if requested_kg is not None and package_kg is not None and package_kg > 0:
        return max(1, math.ceil(round(requested_kg / package_kg, 9)))

    requested_l = normalize_volume_to_l(requested_quantity, requested_unit)
    package_l = normalize_volume_to_l(package_size, package_unit)
    if requested_l is not None and package_l is not None and package_l > 0:
        return max(1, math.ceil(round(requested_l / package_l, 9)))

    return None


@dataclass
class AddToCartResult:
    """What an adapter's add_to_cart actually achieved: `quantity` in `unit` (e.g. 0.5
    "kg", or 3 "unit") — the retailer-confirmed reality, which may differ from what was
    requested (see QuantityConversionRequiredError for the case where no target could be
    determined at all)."""

    quantity: float
    unit: str


class QuantityConversionRequiredError(Exception):
    """Raised by an adapter's add_to_cart when the recipe's requested unit and the
    matched product's retailer selling method are incompatible and no deterministic
    conversion between them exists (e.g. recipe asks for "2 units" of a product this
    retailer only sells by weight — there's no project-wide, deterministic "1 unit = N kg"
    source, so this refuses to guess one). Carries enough structure for the caller to
    explain the mismatch to the user rather than just a message string."""

    def __init__(self, message: str, *, requested_quantity: float, requested_unit: str, retailer_selling_method: str):
        super().__init__(message)
        self.requested_quantity = requested_quantity
        self.requested_unit = requested_unit
        self.retailer_selling_method = retailer_selling_method
