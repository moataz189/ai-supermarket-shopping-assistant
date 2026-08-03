from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import FakeLLM, FakeRecipeClient, FakeSupermarketDataClient


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
    candidates = {
        ("eggs", "shufersal"): [{"item_code": "S-EGG", "name": "Eggs Large 12pk", "price": 12.0}],
        ("Eggs Large 12pk", "shufersal"): [
            {"item_code": "S-EGG", "name": "Eggs Large 12pk", "price": 12.0}
        ],
        ("eggs", "rami_levy"): [{"item_code": "R-EGG", "name": "Eggs Large 12pk", "price": 11.0}],
        ("Eggs Large 12pk", "rami_levy"): [
            {"item_code": "R-EGG", "name": "Eggs Large 12pk", "price": 11.0}
        ],
        ("tomatoes", "shufersal"): [{"item_code": "S-TOM", "name": "Tomatoes 1kg", "price": 8.0}],
        ("Tomatoes 1kg", "shufersal"): [
            {"item_code": "S-TOM", "name": "Tomatoes 1kg", "price": 8.0}
        ],
        ("tomatoes", "rami_levy"): [{"item_code": "R-TOM", "name": "Tomatoes 1kg", "price": 7.0}],
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
    app = build_graph(client, llm, MemorySaver(), recipe_client=recipe_client)
    config = {"configurable": {"thread_id": "t1"}}

    result = await app.ainvoke({"raw_message": "shakshuka for 8"}, config=config)

    assert result["recipe_ambiguous"] is False
    assert result["chosen_recipe"]["id"] == 1
    assert result["chosen_recipe"]["title"] == "Shakshuka"
    assert result["chosen_recipe"]["servings"] == 8

    items = result["parsed_request"]["items"]
    by_name = {i["name"]: i for i in items}
    assert by_name["eggs"]["quantity"] == 8.0
    assert by_name["eggs"]["unit"] == "large"
    assert by_name["tomatoes"]["quantity"] == 800.0
    assert by_name["tomatoes"]["unit"] == "g"

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
    app = build_graph(client, llm, MemorySaver(), recipe_client=recipe_client)
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
    assert by_name["tomatoes"]["display_name"] == "עגבניות"


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
    app = build_graph(client, llm, MemorySaver(), recipe_client=recipe_client)
    config = {"configurable": {"thread_id": "t3"}}

    result = await app.ainvoke({"raw_message": "קובה חלבי בבקשה"}, config=config)

    assert result["chosen_recipe"]["title"] == "Mystery Bake"
    assert result["chosen_recipe"]["display_title"] == "Mystery Bake"
    item = result["parsed_request"]["items"][0]
    assert item["name"] == "saffron"
    assert item["display_name"] == "saffron"
