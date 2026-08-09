from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import (
    TEST_INGREDIENT_DICTIONARY,
    FakeLLM,
    FakeRecipeClient,
    FakeSupermarketDataClient,
)


def _shakshuka_recipe_client():
    return FakeRecipeClient(
        search_results={"shakshuka": [{"id": 1, "title": "Shakshuka"}]},
        recipes={
            1: {
                "title": "Shakshuka",
                "servings": 4,
                "ingredients": [
                    {"name": "eggs", "amount": 4.0, "unit": "large"},
                    {"name": "tomatoes", "amount": 400.0, "unit": "g"},
                ],
            }
        },
    )


def _grocery_client_for_scaled_ingredients():
    # Keyed by the Hebrew search_name (see get_recipe_ingredients.py) — the catalog
    # search always tries Hebrew when a translation exists, regardless of the
    # conversation's own language, since the real catalog is Hebrew-only.
    candidates = {
        ("ביצים", "shufersal"): [{"item_code": "S-EGG", "name": "Eggs Large 12pk", "price": 12.0}],
        ("Eggs Large 12pk", "shufersal"): [
            {"item_code": "S-EGG", "name": "Eggs Large 12pk", "price": 12.0}
        ],
        ("ביצים", "rami_levy"): [{"item_code": "R-EGG", "name": "Eggs Large 12pk", "price": 11.0}],
        ("Eggs Large 12pk", "rami_levy"): [
            {"item_code": "R-EGG", "name": "Eggs Large 12pk", "price": 11.0}
        ],
        ("עגבניה", "shufersal"): [{"item_code": "S-TOM", "name": "Tomatoes 1kg", "price": 8.0}],
        ("Tomatoes 1kg", "shufersal"): [
            {"item_code": "S-TOM", "name": "Tomatoes 1kg", "price": 8.0}
        ],
        ("עגבניה", "rami_levy"): [{"item_code": "R-TOM", "name": "Tomatoes 1kg", "price": 7.0}],
        ("Tomatoes 1kg", "rami_levy"): [
            {"item_code": "R-TOM", "name": "Tomatoes 1kg", "price": 7.0}
        ],
    }
    prices = {
        ("shufersal", "S-EGG"): {"unit_price": 12.0, "price": 12.0},
        ("shufersal", "S-TOM"): {"unit_price": 8.0, "price": 8.0},
        ("rami_levy", "R-EGG"): {"unit_price": 11.0, "price": 11.0},
        ("rami_levy", "R-TOM"): {"unit_price": 7.0, "price": 7.0},
    }
    return FakeSupermarketDataClient(candidates, prices)


async def test_recipe_request_resolves_to_scaled_ingredients_and_builds_both_carts():
    llm = FakeLLM(
        ParsedRequestSchema(request_type="recipe", recipe_query="shakshuka", servings=8, items=[])
    )
    recipe_client = _shakshuka_recipe_client()
    client = _grocery_client_for_scaled_ingredients()
    app = build_graph(
        client, llm, MemorySaver(), recipe_client=recipe_client,
        ingredient_dictionary=TEST_INGREDIENT_DICTIONARY,
    )
    config = {"configurable": {"thread_id": "t1"}}

    interrupted = await app.ainvoke({"raw_message": "shakshuka for 8"}, config=config)

    assert interrupted["recipe_ambiguous"] is False
    assert interrupted["chosen_recipe"]["id"] == 1
    assert interrupted["chosen_recipe"]["title"] == "Shakshuka"
    assert interrupted["chosen_recipe"]["servings"] == 8

    items = interrupted["parsed_request"]["items"]
    by_name = {i["name"]: i for i in items}
    assert by_name["eggs"]["quantity"] == 8.0
    assert by_name["eggs"]["unit"] == "large"
    assert by_name["tomatoes"]["quantity"] == 800.0
    assert by_name["tomatoes"]["unit"] == "g"

    # CP10: pauses for ingredient selection before ever touching the supermarket —
    # resuming with everything selected reproduces this test's pre-CP10 behavior.
    assert interrupted["__interrupt__"][0].value["reason"] == "recipe_ingredient_selection"
    result = await app.ainvoke(Command(resume=["eggs", "tomatoes"]), config=config)

    assert "__interrupt__" in result
    shufersal = result["retailer_carts"]["shufersal"]
    rami_levy = result["retailer_carts"]["rami_levy"]
    assert shufersal["missing_items"] == []
    assert rami_levy["missing_items"] == []
    assert shufersal["total"] == 20.0
    assert rami_levy["total"] == 18.0

    final = await app.ainvoke(Command(resume="shufersal"), config=config)
    assert final["final_result"]["chosen_retailer"] == "shufersal"


async def test_recipe_display_fields_localized_while_canonical_names_stay_english():
    llm = FakeLLM(
        ParsedRequestSchema(request_type="recipe", recipe_query="שקשוקה", servings=4, items=[])
    )
    recipe_client = _shakshuka_recipe_client()
    client = _grocery_client_for_scaled_ingredients()
    app = build_graph(
        client, llm, MemorySaver(), recipe_client=recipe_client,
        ingredient_dictionary=TEST_INGREDIENT_DICTIONARY,
    )
    config = {"configurable": {"thread_id": "t2"}}

    result = await app.ainvoke({"raw_message": "אני רוצה שקשוקה ל-4"}, config=config)

    assert result["raw_message"] == "אני רוצה שקשוקה ל-4"
    assert result["parsed_request"]["recipe_query"] == "shakshuka"

    assert result["chosen_recipe"]["title"] == "Shakshuka"
    assert result["chosen_recipe"]["display_title"] == "שקשוקה"

    items = result["parsed_request"]["items"]
    by_name = {i["name"]: i for i in items}
    assert by_name["eggs"]["name"] == "eggs"
    assert by_name["eggs"]["display_name"] == "ביצים"
    assert by_name["tomatoes"]["name"] == "tomatoes"
    # Singular, matching the real catalog's convention — not "עגבניות" (plural), which a
    # substring search against the real Hebrew-only catalog never matches (see
    # app/agent/i18n.py's INGREDIENT_TRANSLATIONS comment).
    assert by_name["tomatoes"]["display_name"] == "עגבניה"


async def test_hebrew_recipe_request_searches_the_catalog_by_localized_name_not_english():
    # Real user report: asking for a recipe in Hebrew that needs tomatoes reported them
    # missing even though "עגבניה" genuinely exists in the catalog — root-caused to
    # resolve_items/build_retailer_cart searching with the item's English canonical name
    # ("tomatoes") instead of its localized display_name ("עגבניה"), which the Hebrew-only
    # real catalog never matches. This fake catalog deliberately has *no* "tomatoes"-keyed
    # entry at all — only "עגבניה" — so this only passes if the localized name is what's
    # actually searched for.
    llm = FakeLLM(
        ParsedRequestSchema(request_type="recipe", recipe_query="shakshuka", servings=4, items=[])
    )
    recipe_client = _shakshuka_recipe_client()
    candidates = {
        ("ביצים", "shufersal"): [{"item_code": "S-EGG", "name": "ביצים", "price": 12.0}],
        ("ביצים", "rami_levy"): [{"item_code": "R-EGG", "name": "ביצים", "price": 11.0}],
        ("עגבניה", "shufersal"): [{"item_code": "S-TOM", "name": "עגבניה", "price": 8.0}],
        ("עגבניה", "rami_levy"): [{"item_code": "R-TOM", "name": "עגבניה", "price": 7.0}],
    }
    prices = {
        ("shufersal", "S-EGG"): {"unit_price": 12.0, "price": 12.0},
        ("shufersal", "S-TOM"): {"unit_price": 8.0, "price": 8.0},
        ("rami_levy", "R-EGG"): {"unit_price": 11.0, "price": 11.0},
        ("rami_levy", "R-TOM"): {"unit_price": 7.0, "price": 7.0},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(
        client, llm, MemorySaver(), recipe_client=recipe_client,
        ingredient_dictionary=TEST_INGREDIENT_DICTIONARY,
    )
    config = {"configurable": {"thread_id": "t1b"}}

    await app.ainvoke({"raw_message": "אני רוצה שקשוקה"}, config=config)
    result = await app.ainvoke(Command(resume=["eggs", "tomatoes"]), config=config)

    shufersal = result["retailer_carts"]["shufersal"]
    assert shufersal["missing_items"] == []
    tomato_line = next(line for line in shufersal["items"] if line["item_code"] == "S-TOM")
    assert tomato_line["product_name"] == "עגבניה"


async def test_english_recipe_request_still_searches_the_catalog_by_hebrew_name():
    # Follow-up real user report: the Hebrew-conversation fix above wasn't enough — an
    # English-language recipe request ("pasta for 4 people") hit the identical bug,
    # because display_name follows *this conversation's* language and stays English
    # there (INGREDIENT_TRANSLATIONS has no "en" entries by design). The real catalog is
    # Hebrew-only regardless of what language the user is chatting in, so the search
    # query (search_name) must always try Hebrew, independent of display_name/language.
    # Same fake catalog as the Hebrew test above (only Hebrew-keyed candidates exist) —
    # this only passes if search_name, not display_name, drives the search.
    llm = FakeLLM(
        ParsedRequestSchema(request_type="recipe", recipe_query="shakshuka", servings=4, items=[])
    )
    recipe_client = _shakshuka_recipe_client()
    candidates = {
        ("ביצים", "shufersal"): [{"item_code": "S-EGG", "name": "ביצים", "price": 12.0}],
        ("ביצים", "rami_levy"): [{"item_code": "R-EGG", "name": "ביצים", "price": 11.0}],
        ("עגבניה", "shufersal"): [{"item_code": "S-TOM", "name": "עגבניה", "price": 8.0}],
        ("עגבניה", "rami_levy"): [{"item_code": "R-TOM", "name": "עגבניה", "price": 7.0}],
    }
    prices = {
        ("shufersal", "S-EGG"): {"unit_price": 12.0, "price": 12.0},
        ("shufersal", "S-TOM"): {"unit_price": 8.0, "price": 8.0},
        ("rami_levy", "R-EGG"): {"unit_price": 11.0, "price": 11.0},
        ("rami_levy", "R-TOM"): {"unit_price": 7.0, "price": 7.0},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(
        client, llm, MemorySaver(), recipe_client=recipe_client,
        ingredient_dictionary=TEST_INGREDIENT_DICTIONARY,
    )
    config = {"configurable": {"thread_id": "t1c"}}

    interrupted = await app.ainvoke({"raw_message": "shakshuka please"}, config=config)

    # Sanity check this really is an English-detected conversation (the exact condition
    # that broke display_name-based search).
    assert interrupted["parsed_request"]["language"] == "en"
    by_name = {i["name"]: i for i in interrupted["parsed_request"]["items"]}
    assert by_name["tomatoes"]["display_name"] == "tomatoes"  # English — no "en" translation exists

    result = await app.ainvoke(Command(resume=["eggs", "tomatoes"]), config=config)
    shufersal = result["retailer_carts"]["shufersal"]
    assert shufersal["missing_items"] == []
    tomato_line = next(line for line in shufersal["items"] if line["item_code"] == "S-TOM")
    assert tomato_line["product_name"] == "עגבניה"


async def test_recipe_display_falls_back_to_english_when_no_localization_available():
    llm = FakeLLM(
        ParsedRequestSchema(request_type="recipe", recipe_query="Mystery Bake", servings=2, items=[])
    )
    recipe_client = FakeRecipeClient(
        search_results={"Mystery Bake": [{"id": 9, "title": "Mystery Bake"}]},
        recipes={
            9: {
                "title": "Mystery Bake",
                "servings": 2,
                "ingredients": [{"name": "saffron", "amount": 1.0, "unit": "pinch"}],
            }
        },
    )
    client = FakeSupermarketDataClient({}, {})
    app = build_graph(
        client, llm, MemorySaver(), recipe_client=recipe_client,
    )
    config = {"configurable": {"thread_id": "t3"}}

    result = await app.ainvoke({"raw_message": "קובה חלבי בבקשה"}, config=config)

    assert result["chosen_recipe"]["title"] == "Mystery Bake"
    assert result["chosen_recipe"]["display_title"] == "Mystery Bake"
    item = result["parsed_request"]["items"][0]
    assert item["name"] == "saffron"
    assert item["display_name"] == "saffron"
