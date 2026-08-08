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
