"""End-to-end graph tests for recipe-quantity propagation (CP9 follow-up, 2026-08-08).

Reproduces and fixes a real bug: build_retailer_cart previously hardcoded qty=1 for every
cart line regardless of what a recipe actually asked for, so a recipe's scaled ingredient
amounts (e.g. "800 g tomatoes" for 8 servings) never reached the Retailer-Cart MCP at all
— only ever "1". These tests pin down that the real recipe quantity/unit now survives:
Recipe MCP -> parsed_request["items"] -> build_retailer_cart's cart line -> the item dict
sent to the Retailer-Cart MCP client, and that it does NOT survive as a special case for
non-recipe requests (grocery-list/weekly-shop items must keep sending quantity=1/unit=None,
unchanged).
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import (
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


async def test_recipe_ingredient_quantity_survives_into_graph_state():
    # Requirement 1: Recipe MCP quantity survives into graph state.
    llm = FakeLLM(ParsedRequestSchema(request_type="recipe", recipe_query="shakshuka", servings=4, items=[]))
    app = build_graph(
        _grocery_client_for_scaled_ingredients(), llm, MemorySaver(), recipe_client=_shakshuka_recipe_client()
    )
    config = {"configurable": {"thread_id": "t1"}}

    result = await app.ainvoke({"raw_message": "shakshuka"}, config=config)

    items = {i["name"]: i for i in result["parsed_request"]["items"]}
    assert items["tomatoes"]["quantity"] == 400.0
    assert items["tomatoes"]["unit"] == "g"
    assert items["eggs"]["quantity"] == 4.0
    assert items["eggs"]["unit"] == "large"


async def test_recipe_scaling_survives_downstream_into_the_cart_line():
    # Requirement 2: original 4 servings -> requested 8 -> 400 g becomes 800 g, and that
    # scaled amount (not qty=1) is what build_retailer_cart puts on the cart line.
    llm = FakeLLM(ParsedRequestSchema(request_type="recipe", recipe_query="shakshuka", servings=8, items=[]))
    app = build_graph(
        _grocery_client_for_scaled_ingredients(), llm, MemorySaver(), recipe_client=_shakshuka_recipe_client()
    )
    config = {"configurable": {"thread_id": "t2"}}

    result = await app.ainvoke({"raw_message": "shakshuka for 8"}, config=config)

    shufersal_lines = {line["name"]: line for line in result["retailer_carts"]["shufersal"]["items"]}
    assert shufersal_lines["tomatoes"]["requested_quantity"] == 800.0
    assert shufersal_lines["tomatoes"]["requested_unit"] == "g"
    assert shufersal_lines["eggs"]["requested_quantity"] == 8.0
    assert shufersal_lines["eggs"]["requested_unit"] == "large"


async def test_build_retailer_cart_no_longer_hardcodes_qty_1_quantity_for_recipe_items():
    # Requirement 3: build_retailer_cart no longer hardcodes qty=1 for recipe items —
    # the real requested amount reaches the item dict sent to the Retailer-Cart MCP.
    llm = FakeLLM(ParsedRequestSchema(request_type="recipe", recipe_query="shakshuka", servings=4, items=[]))
    retailer_cart_client = FakeRetailerCartClient({"retailer": "shufersal", "added": [], "failed": [],
                                                    "blocked": False, "blocked_reason": None, "cart_url": None})
    app = build_graph(
        _grocery_client_for_scaled_ingredients(), llm, MemorySaver(),
        recipe_client=_shakshuka_recipe_client(), retailer_cart_client=retailer_cart_client,
    )
    config = {"configurable": {"thread_id": "t3"}}

    await app.ainvoke({"raw_message": "shakshuka"}, config=config)
    await app.ainvoke(Command(resume="shufersal"), config=config)

    assert len(retailer_cart_client.calls) == 1
    _, called_items = retailer_cart_client.calls[0]
    by_name = {i["name"]: i for i in called_items}
    assert by_name["tomatoes"]["quantity"] == 400.0
    assert by_name["tomatoes"]["unit"] == "g"
    assert by_name["eggs"]["quantity"] == 4.0
    assert by_name["eggs"]["unit"] == "large"


async def test_requested_quantity_stays_separate_from_cart_quantity_in_the_result():
    # Requirement 8: requested quantity remains separate from cart quantity — the graph
    # must pass through whatever the Retailer-Cart MCP reports without collapsing the two.
    llm = FakeLLM(ParsedRequestSchema(request_type="recipe", recipe_query="shakshuka", servings=4, items=[]))
    canned_result = {
        "retailer": "rami_levy",
        "added": [{
            "name": "tomatoes", "item_code": "R-TOM", "status": "added", "matched_by": "exact_name",
            "quantity_confirmed": 0.5, "requested_quantity": 400.0, "requested_unit": "g",
            "cart_quantity": 0.5, "cart_unit": "kg",
        }],
        "failed": [], "blocked": False, "blocked_reason": None, "cart_url": "https://example.test/cart",
    }
    retailer_cart_client = FakeRetailerCartClient(canned_result)
    app = build_graph(
        _grocery_client_for_scaled_ingredients(), llm, MemorySaver(),
        recipe_client=_shakshuka_recipe_client(), retailer_cart_client=retailer_cart_client,
    )
    config = {"configurable": {"thread_id": "t4"}}

    await app.ainvoke({"raw_message": "shakshuka"}, config=config)
    final = await app.ainvoke(Command(resume="rami_levy"), config=config)

    added = final["final_result"]["retailer_cart_result"]["added"][0]
    assert added["requested_quantity"] == 400.0
    assert added["requested_unit"] == "g"
    assert added["cart_quantity"] == 0.5
    assert added["cart_unit"] == "kg"
    assert added["requested_quantity"] != added["cart_quantity"]


async def test_recipe_info_is_shown_on_the_retailer_choice_interrupt_before_a_choice():
    # Requirement 9: quantities shown before/alongside the comparison — must be visible
    # on the retailer_choice interrupt itself, not only after the user has already picked.
    llm = FakeLLM(ParsedRequestSchema(request_type="recipe", recipe_query="shakshuka", servings=8, items=[]))
    app = build_graph(
        _grocery_client_for_scaled_ingredients(), llm, MemorySaver(), recipe_client=_shakshuka_recipe_client()
    )
    config = {"configurable": {"thread_id": "t5b"}}

    result = await app.ainvoke({"raw_message": "shakshuka for 8"}, config=config)

    payload = result["__interrupt__"][0].value
    assert payload["reason"] == "retailer_choice"
    recipe = payload["recipe"]
    assert recipe["title"] == "Shakshuka"
    ingredients_by_name = {i["name"]: i for i in recipe["ingredients"]}
    assert ingredients_by_name["tomatoes"]["quantity"] == 800.0
    assert ingredients_by_name["tomatoes"]["unit"] == "g"


async def test_finalize_exposes_the_scaled_recipe_ingredient_list():
    llm = FakeLLM(ParsedRequestSchema(request_type="recipe", recipe_query="shakshuka", servings=8, items=[]))
    app = build_graph(
        _grocery_client_for_scaled_ingredients(), llm, MemorySaver(), recipe_client=_shakshuka_recipe_client()
    )
    config = {"configurable": {"thread_id": "t5"}}

    await app.ainvoke({"raw_message": "shakshuka for 8"}, config=config)
    result = await app.ainvoke(Command(resume="decline"), config=config)

    recipe = result["final_result"]["recipe"]
    assert recipe["title"] == "Shakshuka"
    assert recipe["servings"] == 8
    ingredients_by_name = {i["name"]: i for i in recipe["ingredients"]}
    assert ingredients_by_name["tomatoes"]["quantity"] == 800.0
    assert ingredients_by_name["tomatoes"]["unit"] == "g"
    assert ingredients_by_name["eggs"]["quantity"] == 8.0
    assert ingredients_by_name["eggs"]["unit"] == "large"


async def test_grocery_list_request_has_no_recipe_info_in_final_result():
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
    config = {"configurable": {"thread_id": "t6"}}

    await app.ainvoke({"raw_message": "milk"}, config=config)
    result = await app.ainvoke(Command(resume="decline"), config=config)

    assert result["final_result"]["recipe"] is None


async def test_grocery_list_items_still_send_quantity_1_unit_none_no_regression():
    # Requirement 13/14: ordinary grocery-list/weekly-shop behavior must not regress —
    # still sends the pre-existing legacy quantity=1/unit=None shape.
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
    retailer_cart_client = FakeRetailerCartClient({"retailer": "shufersal", "added": [], "failed": [],
                                                    "blocked": False, "blocked_reason": None, "cart_url": None})
    app = build_graph(
        FakeSupermarketDataClient(candidates, prices), llm, MemorySaver(),
        retailer_cart_client=retailer_cart_client,
    )
    config = {"configurable": {"thread_id": "t7"}}

    await app.ainvoke({"raw_message": "milk"}, config=config)
    await app.ainvoke(Command(resume="shufersal"), config=config)

    _, called_items = retailer_cart_client.calls[0]
    assert called_items == [{"name": "milk", "item_code": "S-MILK", "quantity": 1, "unit": None}]


async def test_weekly_shop_profile_items_still_send_quantity_1_unit_none_no_regression():
    llm = FakeLLM(ParsedRequestSchema(request_type="grocery_list", items=[], budget=100))
    # Matches the "one_person" STARTER_LISTS entry in resolve_weekly_shop_profile.py:
    # לחם, חלב, ביצים, חזה עוף, אורז, פסטה, עגבניה, בננה.
    item_names = ["לחם", "חלב", "ביצים", "חזה עוף", "אורז", "פסטה", "עגבניה", "בננה"]
    candidates: dict[tuple[str, str], list[dict]] = {}
    prices: dict[tuple[str, str], dict] = {}
    for i, name in enumerate(item_names):
        for retailer, prefix, price in [("shufersal", "S", 10.0 + i), ("rami_levy", "R", 9.0 + i)]:
            item_code = f"{prefix}-{i}"
            candidates[(name, retailer)] = [{"item_code": item_code, "name": name, "price": price}]
            prices[(retailer, item_code)] = {"unit_price": price, "price": price}
    retailer_cart_client = FakeRetailerCartClient({"retailer": "shufersal", "added": [], "failed": [],
                                                    "blocked": False, "blocked_reason": None, "cart_url": None})
    app = build_graph(
        FakeSupermarketDataClient(candidates, prices), llm, MemorySaver(),
        retailer_cart_client=retailer_cart_client,
    )
    config = {"configurable": {"thread_id": "t8"}}

    await app.ainvoke({"raw_message": "weekly shop"}, config=config)
    interrupted = await app.ainvoke(Command(resume="one_person"), config=config)
    assert "__interrupt__" in interrupted
    await app.ainvoke(Command(resume="shufersal"), config=config)

    assert len(retailer_cart_client.calls) == 1
    _, called_items = retailer_cart_client.calls[0]
    assert called_items
    for item in called_items:
        assert item["quantity"] == 1
        assert item["unit"] is None
