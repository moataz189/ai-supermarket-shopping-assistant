"""Pure-function tests for the retailer-agnostic quantity conversion helpers used by both
adapters to turn a recipe's requested amount+unit into an actual retailer cart quantity —
see mcp_servers/retailer_cart_mcp/quantity.py's module docstring for the full contract.
"""

import pytest

from mcp_servers.retailer_cart_mcp.quantity import (
    is_count_unit,
    normalize_weight_to_kg,
    round_up_to_increment,
)


class TestNormalizeWeightToKg:
    def test_grams_converts_to_kg(self):
        assert normalize_weight_to_kg(400, "g") == pytest.approx(0.4)

    def test_grams_plural_and_case_insensitive(self):
        assert normalize_weight_to_kg(250, "Grams") == pytest.approx(0.25)

    def test_kilograms_passes_through(self):
        assert normalize_weight_to_kg(1.1, "kg") == pytest.approx(1.1)

    def test_kilogram_singular_and_case_insensitive(self):
        assert normalize_weight_to_kg(2, "Kilogram") == pytest.approx(2.0)

    def test_non_weight_unit_returns_none(self):
        assert normalize_weight_to_kg(2, "unit") is None
        assert normalize_weight_to_kg(2, "large") is None
        assert normalize_weight_to_kg(2, "tbsp") is None
        assert normalize_weight_to_kg(2, "cup") is None

    def test_unit_with_surrounding_whitespace_still_recognized(self):
        assert normalize_weight_to_kg(400, "  g  ") == pytest.approx(0.4)


class TestIsCountUnit:
    def test_recognized_weight_units_are_not_count(self):
        assert is_count_unit("g") is False
        assert is_count_unit("kg") is False
        assert is_count_unit("Grams") is False

    def test_recognized_volume_units_are_not_count(self):
        assert is_count_unit("tbsp") is False
        assert is_count_unit("cup") is False
        assert is_count_unit("ml") is False
        assert is_count_unit("l") is False

    def test_anything_else_is_count_like_by_elimination(self):
        # Real Spoonacular data uses all sorts of whole-item descriptors for count-based
        # ingredients (e.g. eggs come back with unit "large", not "unit") — this must not
        # be an explicit allowlist that misses them (confirmed against the fixture already
        # used in tests/agent/test_graph_recipe_happy_path.py).
        assert is_count_unit("unit") is True
        assert is_count_unit("units") is True
        assert is_count_unit("large") is True
        assert is_count_unit("clove") is True
        assert is_count_unit("") is True


class TestRoundUpToIncrement:
    def test_400g_with_half_kg_increment_rounds_up_to_half_kg(self):
        assert round_up_to_increment(0.4, 0.5) == pytest.approx(0.5)

    def test_600g_with_half_kg_increment_rounds_up_to_one_kg(self):
        assert round_up_to_increment(0.6, 0.5) == pytest.approx(1.0)

    def test_1_1kg_with_half_kg_increment_rounds_up_to_1_5kg(self):
        assert round_up_to_increment(1.1, 0.5) == pytest.approx(1.5)

    def test_530g_with_half_kg_increment_rounds_up_to_one_kg(self):
        assert round_up_to_increment(0.530, 0.5) == pytest.approx(1.0)

    def test_500g_with_half_kg_increment_stays_at_half_kg(self):
        # Exactly on the increment boundary -- never rounds up further.
        assert round_up_to_increment(0.500, 0.5) == pytest.approx(0.5)

    def test_501g_with_half_kg_increment_rounds_up_to_one_kg(self):
        # One gram over the boundary is enough to require the next whole increment --
        # rounding must never leave the recipe short.
        assert round_up_to_increment(0.501, 0.5) == pytest.approx(1.0)

    def test_exact_multiple_does_not_round_up_further(self):
        # Guards against floating-point artifacts (e.g. 0.5/0.5 landing a hair above 1.0
        # and ceiling to a spurious extra increment) — an exact multiple of the increment
        # must stay exactly that multiple, never bump up one more step.
        assert round_up_to_increment(0.5, 0.5) == pytest.approx(0.5)
        assert round_up_to_increment(1.0, 0.5) == pytest.approx(1.0)
        assert round_up_to_increment(0.3, 0.1) == pytest.approx(0.3)

    def test_never_rounds_down(self):
        assert round_up_to_increment(0.51, 0.5) == pytest.approx(1.0)
        assert round_up_to_increment(0.01, 0.5) == pytest.approx(0.5)

    def test_generic_for_any_increment_not_hardcoded_to_half_kg(self):
        assert round_up_to_increment(0.3, 0.25) == pytest.approx(0.5)
        assert round_up_to_increment(1.0, 0.25) == pytest.approx(1.0)
