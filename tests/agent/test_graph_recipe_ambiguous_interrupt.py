from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import FakeLLM, FakeRecipeClient, FakeSupermarketDataClient


def _grocery_client_for_pasta():
    candidates = {
        ("pasta", "shufersal"): [{"item_code": "S-PASTA", "name": "Pasta 500g", "price": 6.0}],
        ("Pasta 500g", "shufersal"): [{"item_code": "S-PASTA", "name": "Pasta 500g", "price": 6.0}],
        ("pasta", "rami_levy"): [{"item_code": "R-PASTA", "name": "Pasta 500g", "price": 5.0}],
        ("Pasta 500g", "rami_levy"): [{"item_code": "R-PASTA", "name": "Pasta 500g", "price": 5.0}],
    }
    prices = {
        ("shufersal", "S-PASTA"): {"unit_price": 6.0, "price": 6.0},
        ("rami_levy", "R-PASTA"): {"unit_price": 5.0, "price": 5.0},
    }
    return FakeSupermarketDataClient(candidates, prices)


async def test_two_recipe_matches_with_no_exact_title_interrupts_then_resume_proceeds():
    llm = FakeLLM(
        ParsedRequestSchema(request_type="recipe", recipe_query="pasta", servings=2, items=[])
    )
    recipe_client = FakeRecipeClient(
        search_results={
            "pasta": [
                {"id": 10, "title": "Chicken Pasta Bake"},
                {"id": 11, "title": "Creamy Pasta"},
            ]
        },
        recipes={
            10: {
                "title": "Chicken Pasta Bake",
                "servings": 2,
                "ingredients": [{"name": "pasta", "amount": 200.0, "unit": "g"}],
            },
            11: {
                "title": "Creamy Pasta",
                "servings": 2,
                "ingredients": [{"name": "pasta", "amount": 200.0, "unit": "g"}],
            },
        },
    )
    client = _grocery_client_for_pasta()
    app = build_graph(client, llm, MemorySaver(), recipe_client=recipe_client)
    config = {"configurable": {"thread_id": "t1"}}

    result = await app.ainvoke({"raw_message": "pasta for 2"}, config=config)

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["reason"] == "ambiguous_recipe"
    assert {opt["id"] for opt in payload["options"]} == {"10", "11"}
    assert {opt["label"] for opt in payload["options"]} == {"Chicken Pasta Bake", "Creamy Pasta"}

    final = await app.ainvoke(Command(resume="10"), config=config)

    assert final["chosen_recipe_id"] == 10
    assert final["chosen_recipe"]["title"] == "Chicken Pasta Bake"
    assert "__interrupt__" in final  # now at choose_retailer
    carts = final["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["items"][0]["item_code"] == "S-PASTA"
    assert carts["rami_levy"]["items"][0]["item_code"] == "R-PASTA"


async def test_single_search_result_auto_selects_without_interrupt():
    llm = FakeLLM(
        ParsedRequestSchema(request_type="recipe", recipe_query="shakshuka", servings=4, items=[])
    )
    recipe_client = FakeRecipeClient(
        search_results={"shakshuka": [{"id": 1, "title": "Shakshuka"}]},
        recipes={
            1: {
                "title": "Shakshuka",
                "servings": 4,
                "ingredients": [{"name": "eggs", "amount": 4.0, "unit": "large"}],
            }
        },
    )
    client = FakeSupermarketDataClient(
        {
            ("eggs", "shufersal"): [{"item_code": "S-EGG", "name": "Eggs", "price": 10.0}],
            ("Eggs", "shufersal"): [{"item_code": "S-EGG", "name": "Eggs", "price": 10.0}],
            ("eggs", "rami_levy"): [{"item_code": "R-EGG", "name": "Eggs", "price": 9.0}],
            ("Eggs", "rami_levy"): [{"item_code": "R-EGG", "name": "Eggs", "price": 9.0}],
        },
        {
            ("shufersal", "S-EGG"): {"unit_price": 10.0, "price": 10.0},
            ("rami_levy", "R-EGG"): {"unit_price": 9.0, "price": 9.0},
        },
    )
    app = build_graph(client, llm, MemorySaver(), recipe_client=recipe_client)
    config = {"configurable": {"thread_id": "t2"}}

    result = await app.ainvoke({"raw_message": "shakshuka for 4"}, config=config)

    assert result["recipe_ambiguous"] is False
    assert result["chosen_recipe_id"] == 1


async def test_exact_title_match_among_multiple_candidates_auto_selects_without_interrupt():
    llm = FakeLLM(
        ParsedRequestSchema(request_type="recipe", recipe_query="Shakshuka", servings=4, items=[])
    )
    recipe_client = FakeRecipeClient(
        search_results={
            "Shakshuka": [
                {"id": 1, "title": "Shakshuka"},
                {"id": 2, "title": "Easy Shakshuka"},
            ]
        },
        recipes={
            1: {
                "title": "Shakshuka",
                "servings": 4,
                "ingredients": [{"name": "eggs", "amount": 4.0, "unit": "large"}],
            },
            2: {
                "title": "Easy Shakshuka",
                "servings": 4,
                "ingredients": [{"name": "eggs", "amount": 4.0, "unit": "large"}],
            },
        },
    )
    client = FakeSupermarketDataClient(
        {
            ("eggs", "shufersal"): [{"item_code": "S-EGG", "name": "Eggs", "price": 10.0}],
            ("Eggs", "shufersal"): [{"item_code": "S-EGG", "name": "Eggs", "price": 10.0}],
            ("eggs", "rami_levy"): [{"item_code": "R-EGG", "name": "Eggs", "price": 9.0}],
            ("Eggs", "rami_levy"): [{"item_code": "R-EGG", "name": "Eggs", "price": 9.0}],
        },
        {
            ("shufersal", "S-EGG"): {"unit_price": 10.0, "price": 10.0},
            ("rami_levy", "R-EGG"): {"unit_price": 9.0, "price": 9.0},
        },
    )
    app = build_graph(client, llm, MemorySaver(), recipe_client=recipe_client)
    config = {"configurable": {"thread_id": "t3"}}

    result = await app.ainvoke({"raw_message": "Shakshuka for 4"}, config=config)

    assert result["recipe_ambiguous"] is False
    assert result["chosen_recipe_id"] == 1
    assert result["chosen_recipe"]["title"] == "Shakshuka"
