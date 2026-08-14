"""Pure-function tests for the ingredient-defaults fallback table -- kicks in only when
Spoonacular's own data (both extendedIngredients.measures.metric and
ingredientWidget.json) resolves to a non-actionable placeholder unit ("serving",
"servings", or an empty unit), confirmed live against a real recipe (Spoonacular id
652061, "Miso Cream Pasta") where several ingredients genuinely have no better data
anywhere: Spoonacular's own "amount" for these is a serving count, not a real quantity,
so buying that many units would be wrong (e.g. "4 servings" of onion is not 4 onions).
"""

from mcp_servers.recipe_mcp.ingredient_defaults import (
    default_quantity_for,
    is_non_actionable_unit,
)


def test_serving_and_servings_and_empty_are_non_actionable():
    assert is_non_actionable_unit("serving") is True
    assert is_non_actionable_unit("servings") is True
    assert is_non_actionable_unit("") is True
    assert is_non_actionable_unit(None) is True


def test_case_insensitive_and_whitespace_tolerant():
    assert is_non_actionable_unit("  Servings  ") is True
    assert is_non_actionable_unit("SERVING") is True


def test_real_units_are_actionable():
    assert is_non_actionable_unit("g") is False
    assert is_non_actionable_unit("clove") is False
    assert is_non_actionable_unit("Tbsp") is False
    assert is_non_actionable_unit("unit") is False


def test_per_serving_default_scales_by_requested_servings():
    assert default_quantity_for("pasta", 4) == (500.0, "g")
    assert default_quantity_for("pasta", 8) == (1000.0, "g")
    assert default_quantity_for("rice", 4) == (300.0, "g")
    assert default_quantity_for("olive oil", 4) == (60.0, "ml")
    assert default_quantity_for("parmesan", 4) == (40.0, "g")
    assert default_quantity_for("butter", 4) == (60.0, "g")


def test_per_serving_default_supports_a_count_unit_not_just_weight_or_volume():
    # Real user report: a 40-serving recipe still showed a flat "1 unit" of onion --
    # unlike a plain weight/volume default, this is a genuine fractional *count* per
    # serving, scaled the same way as any other PER_SERVING_DEFAULTS entry.
    assert default_quantity_for("onion", 4) == (1.0, "unit")
    assert default_quantity_for("onion", 40) == (10.0, "unit")
    assert default_quantity_for("onion", 8) == (2.0, "unit")


def test_per_serving_default_is_case_insensitive():
    assert default_quantity_for("Pasta", 4) == (500.0, "g")
    assert default_quantity_for("OLIVE OIL", 4) == (60.0, "ml")


def test_unit_sold_produce_with_no_table_entry_always_buys_exactly_one_regardless_of_servings():
    assert default_quantity_for("melon", 1) == (1.0, "unit")
    assert default_quantity_for("cabbage", 8) == (1.0, "unit")


def test_weight_default_is_flat_and_ignores_servings():
    assert default_quantity_for("tomatoes", 4) == (0.5, "kg")
    assert default_quantity_for("tomatoes", 20) == (0.5, "kg")
    assert default_quantity_for("potatoes", 4) == (0.5, "kg")
    assert default_quantity_for("apples", 4) == (0.5, "kg")


def test_unknown_ingredient_falls_back_to_buying_a_single_unit():
    # An ingredient with no entry anywhere (e.g. "shiso leaves — 36 servings", a real
    # Spoonacular placeholder) must never resolve to literally "36" of something --
    # falls back to the same safe default as a known unit-sold item: buy 1.
    assert default_quantity_for("shiso leaves", 4) == (1.0, "unit")
    assert default_quantity_for("shiso leaves", 36) == (1.0, "unit")
    assert default_quantity_for("an obscure ingredient", 4) == (1.0, "unit")
