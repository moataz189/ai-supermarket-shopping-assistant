"""Unit tests for select_recipe_ingredients.py's pure logic (CP10 — recipe ingredient
selection): building the interrupt's ingredient-option list (everything selected by
default) and filtering the full recipe item list down to only what the user picked on
resume. The actual interrupt/pause/resume behavior needs a real LangGraph runtime
context (interrupt() raises "Called get_config outside of a runnable context" otherwise)
and is covered by the graph-level tests instead
(tests/agent/test_graph_recipe_ingredient_selection.py).
"""

from app.agent.nodes.select_recipe_ingredients import (
    _build_ingredient_options,
    _filter_selected,
    route_after_ingredient_selection,
)


def _items():
    return [
        {"name": "tomatoes", "display_name": "עגבניה", "quantity": 400.0, "unit": "g"},
        {"name": "pasta", "display_name": "פסטה", "quantity": 250.0, "unit": "g"},
        {"name": "olive oil", "display_name": "שמן זית", "quantity": 60.0, "unit": "ml"},
    ]


def test_build_ingredient_options_selects_everything_by_default():
    options = _build_ingredient_options(_items())

    assert all(o["selected"] is True for o in options)


def test_build_ingredient_options_carries_id_name_display_name_quantity_unit():
    options = _build_ingredient_options(_items())

    tomatoes = next(o for o in options if o["name"] == "tomatoes")
    assert tomatoes == {
        "id": "tomatoes",
        "name": "tomatoes",
        "display_name": "עגבניה",
        "quantity": 400.0,
        "unit": "g",
        "selected": True,
    }


def test_build_ingredient_options_falls_back_to_name_when_no_display_name():
    options = _build_ingredient_options([{"name": "saffron", "quantity": 1.0, "unit": "pinch"}])

    assert options[0]["display_name"] == "saffron"


def test_filter_selected_keeps_only_the_chosen_ingredients():
    selected = _filter_selected(_items(), ["tomatoes", "pasta"])

    assert [i["name"] for i in selected] == ["tomatoes", "pasta"]


def test_filter_selected_preserves_quantity_and_unit():
    selected = _filter_selected(_items(), ["tomatoes"])

    assert selected[0]["quantity"] == 400.0
    assert selected[0]["unit"] == "g"


def test_filter_selected_with_everything_selected_returns_the_full_list():
    selected = _filter_selected(_items(), ["tomatoes", "pasta", "olive oil"])

    assert len(selected) == 3


def test_filter_selected_with_nothing_selected_returns_empty_list():
    selected = _filter_selected(_items(), [])

    assert selected == []


def test_filter_selected_with_none_answer_returns_empty_list():
    # A resume answer that's missing/None (rather than an explicit empty list) must not
    # crash — treated the same as "selected nothing".
    selected = _filter_selected(_items(), None)

    assert selected == []


def test_filter_selected_ignores_unknown_ids_instead_of_crashing():
    # Validation: a stale/unknown id in the resume answer (e.g. from a previous turn's
    # ingredient list) is silently dropped, not trusted blindly.
    selected = _filter_selected(_items(), ["tomatoes", "not-a-real-ingredient"])

    assert [i["name"] for i in selected] == ["tomatoes"]


def test_route_after_ingredient_selection_goes_to_resolve_items_when_something_selected():
    state = {"parsed_request": {"items": [{"name": "tomatoes"}]}}

    assert route_after_ingredient_selection(state) == "resolve_items"


def test_route_after_ingredient_selection_goes_to_no_ingredients_to_buy_when_empty():
    state = {"parsed_request": {"items": []}}

    assert route_after_ingredient_selection(state) == "no_ingredients_to_buy"
