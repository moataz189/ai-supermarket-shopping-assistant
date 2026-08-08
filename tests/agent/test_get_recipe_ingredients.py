"""Node-level tests for get_recipe_ingredients.py's static-dictionary translation (CP9
follow-up, 2026-08-08) — replaces the earlier LLM-based translation. Each item carries a
normalized translation object (name/display_name/search_name/english_name/
translation_resolved) rather than a bare translated string.
"""

from app.agent.nodes.get_recipe_ingredients import make_get_recipe_ingredients
from tests.agent.fakes import FakeRecipeClient


def _shakshuka_recipe_client():
    return FakeRecipeClient(
        search_results={"shakshuka": [{"id": 1, "title": "Shakshuka"}]},
        recipes={
            1: {
                "title": "Shakshuka",
                "servings": 4,
                "ingredients": [
                    {"name": "tomato", "amount": 400.0, "unit": "g"},
                    {"name": "an obscure spice", "amount": 1.0, "unit": "pinch"},
                ],
            }
        },
    )


async def test_ingredient_found_in_dictionary_uses_its_hebrew_search_term():
    dictionary = {"tomato": "עגבנייה"}
    node = make_get_recipe_ingredients(_shakshuka_recipe_client(), dictionary)
    state = {"parsed_request": {"servings": 4, "language": "en"}, "chosen_recipe_id": 1}

    result = await node(state)

    items_by_name = {i["name"]: i for i in result["parsed_request"]["items"]}
    tomato = items_by_name["tomato"]
    assert tomato["search_name"] == "עגבנייה"
    assert tomato["english_name"] == "tomato"
    assert tomato["translation_resolved"] is True


async def test_ingredient_missing_from_dictionary_falls_back_to_english_and_is_flagged():
    dictionary = {"tomato": "עגבנייה"}  # deliberately no entry for "an obscure spice"
    node = make_get_recipe_ingredients(_shakshuka_recipe_client(), dictionary)
    state = {"parsed_request": {"servings": 4, "language": "en"}, "chosen_recipe_id": 1}

    result = await node(state)

    items_by_name = {i["name"]: i for i in result["parsed_request"]["items"]}
    spice = items_by_name["an obscure spice"]
    assert spice["search_name"] == "an obscure spice"
    assert spice["english_name"] == "an obscure spice"
    assert spice["translation_resolved"] is False


async def test_original_english_name_is_always_preserved_regardless_of_resolution():
    dictionary = {"tomato": "עגבנייה"}
    node = make_get_recipe_ingredients(_shakshuka_recipe_client(), dictionary)
    state = {"parsed_request": {"servings": 4, "language": "en"}, "chosen_recipe_id": 1}

    result = await node(state)

    for item in result["parsed_request"]["items"]:
        assert item["english_name"] == item["name"]


async def test_empty_dictionary_leaves_every_ingredient_unresolved_without_crashing():
    node = make_get_recipe_ingredients(_shakshuka_recipe_client(), {})
    state = {"parsed_request": {"servings": 4, "language": "en"}, "chosen_recipe_id": 1}

    result = await node(state)

    items = result["parsed_request"]["items"]
    assert len(items) == 2
    assert all(item["translation_resolved"] is False for item in items)
    assert all(item["search_name"] == item["name"] for item in items)


async def test_hebrew_conversation_shows_the_dictionary_hebrew_term_as_display_name_too():
    # Real user report, 2026-08-08: in a Hebrew conversation, only the handful of
    # ingredients covered by the tiny legacy phrase table (app/agent/i18n.py) showed up
    # in Hebrew — everything else the big dictionary *did* resolve for search still
    # displayed in English, an inconsistent half-translated ingredient list. "tomato" has
    # no entry in the small legacy table, only the big dictionary.
    dictionary = {"tomato": "עגבנייה"}
    node = make_get_recipe_ingredients(_shakshuka_recipe_client(), dictionary)
    state = {"parsed_request": {"servings": 4, "language": "he"}, "chosen_recipe_id": 1}

    result = await node(state)

    items_by_name = {i["name"]: i for i in result["parsed_request"]["items"]}
    assert items_by_name["tomato"]["display_name"] == "עגבנייה"


async def test_english_conversation_keeps_english_display_name_even_when_dictionary_resolves():
    # display_name follows the conversation's own language — an English conversation must
    # not start showing Hebrew text just because the (Hebrew-only) search dictionary
    # resolved the ingredient.
    dictionary = {"tomato": "עגבנייה"}
    node = make_get_recipe_ingredients(_shakshuka_recipe_client(), dictionary)
    state = {"parsed_request": {"servings": 4, "language": "en"}, "chosen_recipe_id": 1}

    result = await node(state)

    items_by_name = {i["name"]: i for i in result["parsed_request"]["items"]}
    assert items_by_name["tomato"]["display_name"] == "tomato"


async def test_hebrew_conversation_ingredient_unresolved_in_either_table_stays_english():
    dictionary = {"tomato": "עגבנייה"}  # no entry for "an obscure spice"
    node = make_get_recipe_ingredients(_shakshuka_recipe_client(), dictionary)
    state = {"parsed_request": {"servings": 4, "language": "he"}, "chosen_recipe_id": 1}

    result = await node(state)

    items_by_name = {i["name"]: i for i in result["parsed_request"]["items"]}
    assert items_by_name["an obscure spice"]["display_name"] == "an obscure spice"


async def test_sea_salt_and_pepper_splits_into_two_independent_pantry_items():
    # Targeted special case (CP9 follow-up, 2026-08-08), not a general splitting
    # mechanism — no real product contains both salt and pepper, so this one compound
    # ingredient is expanded into its two real, separately-sold products, each resolved
    # and searched independently through the normal flow.
    dictionary = {"sea salt": "מלח ים", "black pepper": "פלפל שחור"}
    recipe_client = FakeRecipeClient(
        search_results={"ratatouille": [{"id": 2, "title": "Ratatouille Pasta"}]},
        recipes={
            2: {
                "title": "Ratatouille Pasta",
                "servings": 4,
                "ingredients": [
                    {"name": "sea salt and pepper", "amount": 4.0, "unit": "servings"},
                ],
            }
        },
    )
    node = make_get_recipe_ingredients(recipe_client, dictionary)
    state = {"parsed_request": {"servings": 4, "language": "en"}, "chosen_recipe_id": 2}

    result = await node(state)

    items = result["parsed_request"]["items"]
    assert len(items) == 2
    by_name = {i["name"]: i for i in items}
    assert set(by_name) == {"sea salt", "black pepper"}
    assert by_name["sea salt"]["search_name"] == "מלח ים"
    assert by_name["sea salt"]["translation_resolved"] is True
    assert by_name["black pepper"]["search_name"] == "פלפל שחור"
    assert by_name["black pepper"]["translation_resolved"] is True
    # No mathematical split of the recipe's own "4 servings" — each split ingredient is
    # an ordinary pantry item with no quantity/unit at all (the same default whole-unit
    # behavior a plain grocery-list item already gets).
    assert "quantity" not in by_name["sea salt"]
    assert "unit" not in by_name["sea salt"]
    assert "quantity" not in by_name["black pepper"]
    assert "unit" not in by_name["black pepper"]


async def test_ordinary_ingredients_are_unaffected_by_the_sea_salt_and_pepper_special_case():
    dictionary = {"tomato": "עגבנייה"}
    node = make_get_recipe_ingredients(_shakshuka_recipe_client(), dictionary)
    state = {"parsed_request": {"servings": 4, "language": "en"}, "chosen_recipe_id": 1}

    result = await node(state)

    # Unchanged from before this special case existed — no splitting for anything else.
    items = result["parsed_request"]["items"]
    assert len(items) == 2
    assert {i["name"] for i in items} == {"tomato", "an obscure spice"}
