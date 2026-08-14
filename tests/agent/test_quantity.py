"""Pure-function tests for app/agent/quantity.py's comparison-view package estimate --
deliberately independent of mcp_servers/retailer_cart_mcp/quantity.py's own
packages_needed (app/ and mcp_servers/ are separate deployable services that never
import from each other, see app/agent/mcp_clients.py's MCP client boundary), used only
to make the comparison view (before a retailer is ever chosen) show a realistic price/
quantity instead of a single package's, e.g. real user report: a recipe needing 1000 g
of pasta (a 500 g package) showed "× 1000 g" at a single package's price (₪7.90)
instead of "× 2" at ₪15.80.
"""

from app.agent.quantity import estimate_weight_kg_for_count, estimated_package_count, is_count_unit


def test_1000g_needed_in_500g_packages_is_two():
    assert estimated_package_count(1000, "g", 500, "g") == 2


def test_exact_multiple_needs_exactly_that_many_packages():
    assert estimated_package_count(500, "g", 500, "g") == 1


def test_never_rounds_down_partial_package_still_needs_one_more():
    assert estimated_package_count(501, "g", 500, "g") == 2


def test_kg_and_g_units_are_compatible():
    assert estimated_package_count(1, "kg", 500, "g") == 2


def test_ml_and_l_units_are_compatible():
    assert estimated_package_count(1500, "ml", 500, "ml") == 3
    assert estimated_package_count(1.5, "l", 500, "ml") == 3


def test_at_least_one_package_even_for_a_tiny_request():
    assert estimated_package_count(10, "g", 500, "g") == 1


def test_incompatible_dimensions_return_none():
    assert estimated_package_count(1000, "g", 1, "unit") is None
    assert estimated_package_count(500, "g", 500, "ml") is None


def test_count_units_are_recognized():
    assert is_count_unit("unit") is True
    assert is_count_unit("large") is True
    assert is_count_unit("clove") is True


def test_weight_and_volume_units_are_not_count():
    assert is_count_unit("kg") is False
    assert is_count_unit("g") is False
    assert is_count_unit("cup") is False
    assert is_count_unit("ml") is False


def test_estimate_weight_kg_for_count_matches_the_retailer_cart_mcp_constant():
    # Same value as mcp_servers/retailer_cart_mcp/quantity.py's
    # estimate_weight_kg_for_count -- the comparison-view price and the real cart-add
    # must agree, or the price shown up front won't match what actually gets bought.
    assert estimate_weight_kg_for_count(1, "unit") == 0.5
    assert estimate_weight_kg_for_count(2, "unit") == 1.0


def test_small_portion_units_get_a_much_smaller_estimate_than_a_whole_item():
    # Real user report (2026-08-14): "4 clove" of garlic against a weight-sold product
    # priced as if it were 2 kg (4 x the whole-item 0.5 kg/unit default) -- ₪272.50 for
    # garlic. A clove is a small fraction of a whole bulb, not a whole produce item.
    assert estimate_weight_kg_for_count(4, "clove") == 0.08
    assert estimate_weight_kg_for_count(4, "unit") == 2.0


def test_small_portion_units_are_recognized_regardless_of_case_or_whitespace():
    assert estimate_weight_kg_for_count(1, "  Clove  ") == estimate_weight_kg_for_count(1, "clove")
    assert estimate_weight_kg_for_count(1, "Sprig") == estimate_weight_kg_for_count(1, "sprig")
