"""Graph-level tests for recipe ingredient selection (CP10): after a recipe's scaled
ingredients are fetched, the graph pauses so the user can pick only what they actually
need to buy — everything selected by default — before resolve_items/build_*_cart ever
run. Only the selected ingredients continue; unselected ones never reach the supermarket
or retailer-cart flow at all.
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import (
    TEST_INGREDIENT_DICTIONARY,
    FakeLLM,
    FakeRecipeClient,
    FakeRetailerCartClient,
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
                    {"name": "olive oil", "amount": 60.0, "unit": "ml"},
                ],
            }
        },
    )


def _grocery_client():
    candidates = {
        ("ביצים", "shufersal"): [{"item_code": "S-EGG", "name": "Eggs Large 12pk", "price": 12.0}],
        ("Eggs Large 12pk", "shufersal"): [{"item_code": "S-EGG", "name": "Eggs Large 12pk", "price": 12.0}],
        ("ביצים", "rami_levy"): [{"item_code": "R-EGG", "name": "Eggs Large 12pk", "price": 11.0}],
        ("Eggs Large 12pk", "rami_levy"): [{"item_code": "R-EGG", "name": "Eggs Large 12pk", "price": 11.0}],
        ("עגבניה", "shufersal"): [{"item_code": "S-TOM", "name": "Tomatoes 1kg", "price": 8.0}],
        ("Tomatoes 1kg", "shufersal"): [{"item_code": "S-TOM", "name": "Tomatoes 1kg", "price": 8.0}],
        ("עגבניה", "rami_levy"): [{"item_code": "R-TOM", "name": "Tomatoes 1kg", "price": 7.0}],
        ("Tomatoes 1kg", "rami_levy"): [{"item_code": "R-TOM", "name": "Tomatoes 1kg", "price": 7.0}],
        # Deliberately no candidates at all for "olive oil"/"שמן זית" — if it's ever
        # searched, it would come back "missing", which the "never reaches resolve_items"
        # tests below assert against directly via item_candidates instead.
    }
    prices = {
        ("shufersal", "S-EGG"): {"unit_price": 12.0, "price": 12.0},
        ("shufersal", "S-TOM"): {"unit_price": 8.0, "price": 8.0},
        ("rami_levy", "R-EGG"): {"unit_price": 11.0, "price": 11.0},
        ("rami_levy", "R-TOM"): {"unit_price": 7.0, "price": 7.0},
    }
    return FakeSupermarketDataClient(candidates, prices)


def _build_app(recipe_client=None):
    llm = FakeLLM(ParsedRequestSchema(request_type="recipe", recipe_query="shakshuka", servings=4, items=[]))
    app = build_graph(
        _grocery_client(), llm, MemorySaver(),
        recipe_client=recipe_client or _shakshuka_recipe_client(),
        ingredient_dictionary=TEST_INGREDIENT_DICTIONARY,
    )
    return app


async def test_recipe_flow_pauses_after_ingredients_are_fetched_and_scaled():
    app = _build_app()
    config = {"configurable": {"thread_id": "t1"}}

    result = await app.ainvoke({"raw_message": "shakshuka for 4"}, config=config)

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["reason"] == "recipe_ingredient_selection"


async def test_all_ingredients_are_selected_by_default():
    app = _build_app()
    config = {"configurable": {"thread_id": "t2"}}

    result = await app.ainvoke({"raw_message": "shakshuka for 4"}, config=config)

    payload = result["__interrupt__"][0].value
    assert all(ing["selected"] is True for ing in payload["ingredients"])
    assert {ing["name"] for ing in payload["ingredients"]} == {"eggs", "tomatoes", "olive oil"}


async def test_quantities_and_units_appear_in_the_clarification_response():
    app = _build_app()
    config = {"configurable": {"thread_id": "t3"}}

    result = await app.ainvoke({"raw_message": "shakshuka for 4"}, config=config)

    payload = result["__interrupt__"][0].value
    by_name = {ing["name"]: ing for ing in payload["ingredients"]}
    assert by_name["tomatoes"]["quantity"] == 400.0
    assert by_name["tomatoes"]["unit"] == "g"
    assert by_name["eggs"]["quantity"] == 4.0
    assert by_name["eggs"]["unit"] == "large"


async def test_recipe_title_and_servings_appear_alongside_the_ingredients():
    app = _build_app()
    config = {"configurable": {"thread_id": "t3b"}}

    result = await app.ainvoke({"raw_message": "shakshuka for 4"}, config=config)

    payload = result["__interrupt__"][0].value
    assert payload["recipe"]["title"] == "Shakshuka"
    assert payload["recipe"]["servings"] == 4


async def test_unselected_ingredient_never_reaches_resolve_items():
    app = _build_app()
    config = {"configurable": {"thread_id": "t4"}}

    await app.ainvoke({"raw_message": "shakshuka for 4"}, config=config)
    result = await app.ainvoke(Command(resume=["eggs", "tomatoes"]), config=config)

    assert "olive oil" not in result["item_candidates"]
    assert "olive oil" not in result["resolved_choices"]


async def test_unselected_ingredient_does_not_appear_as_missing():
    app = _build_app()
    config = {"configurable": {"thread_id": "t5"}}

    await app.ainvoke({"raw_message": "shakshuka for 4"}, config=config)
    result = await app.ainvoke(Command(resume=["eggs", "tomatoes"]), config=config)

    shufersal = result["retailer_carts"]["shufersal"]
    rami_levy = result["retailer_carts"]["rami_levy"]
    assert "olive oil" not in {m["name"] for m in shufersal["missing_items"]}
    assert "olive oil" not in {m["name"] for m in rami_levy["missing_items"]}


async def test_unselected_ingredient_does_not_affect_retailer_totals():
    app = _build_app()
    config = {"configurable": {"thread_id": "t6"}}

    await app.ainvoke({"raw_message": "shakshuka for 4"}, config=config)
    result = await app.ainvoke(Command(resume=["eggs", "tomatoes"]), config=config)

    # Only eggs (12.0) + tomatoes (8.0) — olive oil never priced in at all, whether found
    # or missing.
    assert result["retailer_carts"]["shufersal"]["total"] == 20.0


async def test_unselected_ingredient_never_sent_to_retailer_cart_mcp():
    retailer_cart_client = FakeRetailerCartClient({
        "retailer": "shufersal", "added": [], "failed": [],
        "blocked": False, "blocked_reason": None, "cart_url": None,
    })
    llm = FakeLLM(ParsedRequestSchema(request_type="recipe", recipe_query="shakshuka", servings=4, items=[]))
    app = build_graph(
        _grocery_client(), llm, MemorySaver(), recipe_client=_shakshuka_recipe_client(),
        retailer_cart_client=retailer_cart_client, ingredient_dictionary=TEST_INGREDIENT_DICTIONARY,
    )
    config = {"configurable": {"thread_id": "t7"}}

    await app.ainvoke({"raw_message": "shakshuka for 4"}, config=config)
    await app.ainvoke(Command(resume=["eggs", "tomatoes"]), config=config)
    await app.ainvoke(Command(resume="shufersal"), config=config)

    assert len(retailer_cart_client.calls) == 1
    _, called_items = retailer_cart_client.calls[0]
    assert "olive oil" not in {i["name"] for i in called_items}


async def test_selected_ingredients_preserve_their_recipe_quantity_and_unit():
    app = _build_app()
    config = {"configurable": {"thread_id": "t8"}}

    await app.ainvoke({"raw_message": "shakshuka for 4"}, config=config)
    result = await app.ainvoke(Command(resume=["eggs", "tomatoes"]), config=config)

    lines = {line["name"]: line for line in result["retailer_carts"]["shufersal"]["items"]}
    assert lines["tomatoes"]["requested_quantity"] == 400.0
    assert lines["tomatoes"]["requested_unit"] == "g"
    assert lines["eggs"]["requested_quantity"] == 4.0
    assert lines["eggs"]["requested_unit"] == "large"


async def test_select_all_resumes_with_every_ingredient_and_builds_a_full_cart():
    app = _build_app()
    config = {"configurable": {"thread_id": "t9"}}

    interrupted = await app.ainvoke({"raw_message": "shakshuka for 4"}, config=config)
    all_ids = [ing["id"] for ing in interrupted["__interrupt__"][0].value["ingredients"]]
    result = await app.ainvoke(Command(resume=all_ids), config=config)

    shufersal_names = {line["name"] for line in result["retailer_carts"]["shufersal"]["items"]}
    assert shufersal_names == {"eggs", "tomatoes"}  # olive oil has no catalog match either way
    missing_names = {m["name"] for m in result["retailer_carts"]["shufersal"]["missing_items"]}
    assert missing_names == {"olive oil"}


async def test_clear_all_selects_nothing_and_skips_supermarket_and_cart_building_entirely():
    app = _build_app()
    config = {"configurable": {"thread_id": "t10"}}

    await app.ainvoke({"raw_message": "shakshuka for 4"}, config=config)
    result = await app.ainvoke(Command(resume=[]), config=config)

    assert "__interrupt__" not in result
    # resolve_items never ran at all — item_candidates was never even set, not just empty.
    assert "item_candidates" not in result
    assert result["retailer_carts"] == {}
    assert result["final_result"]["carts"] == {}


async def test_clear_all_does_not_build_empty_priced_carts_and_returns_a_friendly_message():
    app = _build_app()
    config = {"configurable": {"thread_id": "t11"}}

    await app.ainvoke({"raw_message": "shakshuka for 4"}, config=config)
    result = await app.ainvoke(Command(resume=[]), config=config)

    assert result["status"] == "success"
    assert result["final_result"]["message"] == "You already have all the ingredients for this recipe."


async def test_normal_grocery_list_flow_never_hits_the_ingredient_selection_interrupt():
    llm = FakeLLM(ParsedRequestSchema(items=["milk"]))
    candidates = {
        ("milk", "shufersal"): [{"item_code": "S-MILK", "name": "Milk 3%", "price": 6.0}],
        ("Milk 3%", "shufersal"): [{"item_code": "S-MILK", "name": "Milk 3%", "price": 6.0}],
        ("milk", "rami_levy"): [{"item_code": "R-MILK", "name": "Milk 3%", "price": 5.5}],
        ("Milk 3%", "rami_levy"): [{"item_code": "R-MILK", "name": "Milk 3%", "price": 5.5}],
    }
    prices = {
        ("shufersal", "S-MILK"): {"unit_price": 6.0, "price": 6.0},
        ("rami_levy", "R-MILK"): {"unit_price": 5.5, "price": 5.5},
    }
    app = build_graph(FakeSupermarketDataClient(candidates, prices), llm, MemorySaver())
    config = {"configurable": {"thread_id": "t12"}}

    result = await app.ainvoke({"raw_message": "milk"}, config=config)

    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["reason"] == "retailer_choice"  # straight through


async def test_retailer_choice_and_cart_preparation_unchanged_after_ingredient_selection():
    canned_result = {
        "retailer": "shufersal",
        "added": [{"name": "tomatoes", "item_code": "S-TOM", "status": "added", "matched_by": "exact_name",
                   "quantity_confirmed": 400.0, "requested_quantity": 400.0, "requested_unit": "g",
                   "cart_quantity": 400.0, "cart_unit": "g"}],
        "failed": [], "blocked": False, "blocked_reason": None, "cart_url": "https://example.test/cart",
    }
    retailer_cart_client = FakeRetailerCartClient(canned_result)
    llm = FakeLLM(ParsedRequestSchema(request_type="recipe", recipe_query="shakshuka", servings=4, items=[]))
    app = build_graph(
        _grocery_client(), llm, MemorySaver(), recipe_client=_shakshuka_recipe_client(),
        retailer_cart_client=retailer_cart_client, ingredient_dictionary=TEST_INGREDIENT_DICTIONARY,
    )
    config = {"configurable": {"thread_id": "t13"}}

    await app.ainvoke({"raw_message": "shakshuka for 4"}, config=config)
    interrupted = await app.ainvoke(Command(resume=["eggs", "tomatoes"]), config=config)
    assert interrupted["__interrupt__"][0].value["reason"] == "retailer_choice"

    final = await app.ainvoke(Command(resume="shufersal"), config=config)

    assert final["final_result"]["chosen_retailer"] == "shufersal"
    assert final["final_result"]["retailer_cart_result"]["added"][0]["item_code"] == "S-TOM"
