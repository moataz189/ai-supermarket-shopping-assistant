"""Pure-function tests for recipe_mcp's own "is this metric measure precise enough to
use directly" check -- deliberately separate from
mcp_servers/retailer_cart_mcp/quantity.py's own weight/volume sets: that module decides
how to convert a normalized amount into a specific retailer's selling method, this one
only decides whether Spoonacular's own `measures.metric` is already a real weight/volume
(not a count or size descriptor) before ever calling the extra ingredientWidget endpoint.
"""

from mcp_servers.recipe_mcp.quantity import is_precise_metric_unit


def test_grams_short_and_long_forms_are_precise():
    assert is_precise_metric_unit("g") is True
    assert is_precise_metric_unit("gram") is True
    assert is_precise_metric_unit("grams") is True


def test_kilograms_short_and_long_forms_are_precise():
    assert is_precise_metric_unit("kg") is True
    assert is_precise_metric_unit("kilogram") is True
    assert is_precise_metric_unit("kilograms") is True


def test_milliliters_and_liters_are_precise():
    assert is_precise_metric_unit("ml") is True
    assert is_precise_metric_unit("milliliters") is True
    assert is_precise_metric_unit("l") is True
    assert is_precise_metric_unit("liters") is True


def test_case_insensitive_and_whitespace_tolerant():
    assert is_precise_metric_unit("  Grams  ") is True
    assert is_precise_metric_unit("KG") is True


def test_size_descriptors_and_counts_are_not_precise():
    assert is_precise_metric_unit("Tbsp") is False
    assert is_precise_metric_unit("servings") is False
    assert is_precise_metric_unit("medium") is False
    assert is_precise_metric_unit("large") is False
    assert is_precise_metric_unit("cup") is False


def test_none_or_empty_is_not_precise():
    assert is_precise_metric_unit(None) is False
    assert is_precise_metric_unit("") is False
