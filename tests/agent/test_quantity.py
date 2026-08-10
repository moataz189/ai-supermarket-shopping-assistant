"""Pure-function tests for app/agent/quantity.py's comparison-view package estimate --
deliberately independent of mcp_servers/retailer_cart_mcp/quantity.py's own
packages_needed (app/ and mcp_servers/ are separate deployable services that never
import from each other, see app/agent/mcp_clients.py's MCP client boundary), used only
to make the comparison view (before a retailer is ever chosen) show a realistic price/
quantity instead of a single package's, e.g. real user report: a recipe needing 1000 g
of pasta (a 500 g package) showed "× 1000 g" at a single package's price (₪7.90)
instead of "× 2" at ₪15.80.
"""

from app.agent.quantity import estimated_package_count


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
