from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from app.agent.nodes.resolve_weekly_shop_profile import PROFILE_OPTIONS, STARTER_LISTS
from tests.agent.fakes import FakeLLM, FakeSupermarketDataClient


async def test_budget_only_request_asks_for_a_weekly_shop_profile_instead_of_empty_carts():
    llm = FakeLLM(ParsedRequestSchema(items=[], budget=250))
    client = FakeSupermarketDataClient({}, {})
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    result = await app.ainvoke({"raw_message": "Weekly shopping under ₪250"}, config=config)

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["reason"] == "weekly_shop_profile"
    assert payload["question"] == "What kind of weekly shopping do you need?"
    assert payload["options"] == PROFILE_OPTIONS
    # never built a cart from an empty item list
    assert "retailer_carts" not in result or result["retailer_carts"] == {}


async def test_choosing_a_profile_resolves_its_deterministic_starter_list_and_keeps_budget():
    llm = FakeLLM(ParsedRequestSchema(items=[], budget=250))
    client = FakeSupermarketDataClient({}, {})
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t2"}}

    await app.ainvoke({"raw_message": "Weekly shopping under ₪250"}, config=config)
    final = await app.ainvoke(Command(resume="family"), config=config)

    # no candidates stubbed — every item lands in missing_items, which is enough to prove
    # exactly the "family" starter list (not an empty list, not another profile's list)
    # was what got resolved, without needing to stub a full realistic catalog here.
    assert "__interrupt__" in final
    carts = final["__interrupt__"][0].value["carts"]
    missing_names = {m["name"] for m in carts["shufersal"]["missing_items"]}
    assert missing_names == {entry["name"] for entry in STARTER_LISTS["family"]}
    assert carts["shufersal"]["budget"] == 250
    assert carts["shufersal"]["total"] == 0
    assert carts["shufersal"]["over_budget_by"] is None


async def test_starter_list_quantities_scale_by_household_size():
    """Real user report: every profile silently sent the same quantity=1 for every item
    regardless of household size (e.g. tomatoes for one person vs. a family). Each
    STARTER_LISTS entry now carries a real quantity/unit sized for that profile."""
    llm = FakeLLM(ParsedRequestSchema(items=[], budget=250))
    client = FakeSupermarketDataClient({}, {})
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t2b"}}

    await app.ainvoke({"raw_message": "Weekly shopping under ₪250"}, config=config)
    result = await app.ainvoke(Command(resume="one_person"), config=config)
    items = {i["name"]: i for i in result["parsed_request"]["items"]}
    assert items["עגבניה"]["quantity"] == 0.5
    assert items["עגבניה"]["unit"] == "kg"

    config2 = {"configurable": {"thread_id": "t2c"}}
    await app.ainvoke({"raw_message": "Weekly shopping under ₪250"}, config=config2)
    result2 = await app.ainvoke(Command(resume="family"), config=config2)
    items2 = {i["name"]: i for i in result2["parsed_request"]["items"]}
    assert items2["עגבניה"]["quantity"] == 1
    assert items2["עגבניה"]["unit"] == "kg"


async def test_custom_freeform_list_still_has_no_quantity_no_regression():
    llm = FakeLLM(ParsedRequestSchema(items=[], budget=250))
    client = FakeSupermarketDataClient({}, {})
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t2d"}}

    await app.ainvoke({"raw_message": "Weekly shopping under ₪250"}, config=config)
    await app.ainvoke(Command(resume="custom"), config=config)
    result = await app.ainvoke(Command(resume="milk, bread"), config=config)

    for item in result["parsed_request"]["items"]:
        assert item["quantity"] is None


async def test_choosing_custom_asks_for_a_freeform_list_then_builds_carts_from_it():
    llm = FakeLLM(ParsedRequestSchema(items=[], budget=250))
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
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t3"}}

    await app.ainvoke({"raw_message": "Weekly shopping under ₪250"}, config=config)
    custom_prompt = await app.ainvoke(Command(resume="custom"), config=config)

    assert "__interrupt__" in custom_prompt
    custom_payload = custom_prompt["__interrupt__"][0].value
    assert custom_payload["reason"] == "weekly_shop_custom_list"
    assert custom_payload["options"] == []

    final = await app.ainvoke(Command(resume="milk"), config=config)

    assert "__interrupt__" in final
    carts = final["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["items"][0]["item_code"] == "S-MILK"
    assert carts["shufersal"]["budget"] == 250


async def test_typing_a_list_directly_instead_of_clicking_an_option_still_works():
    """The chat box stays open during the clarification — a user who ignores the profile
    buttons and just types their list gets the same result as clicking "custom" then
    typing it, not an unrecognized-answer error."""
    llm = FakeLLM(ParsedRequestSchema(items=[], budget=250))
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
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t4"}}

    await app.ainvoke({"raw_message": "Weekly shopping under ₪250"}, config=config)
    final = await app.ainvoke(Command(resume="milk"), config=config)

    assert "__interrupt__" in final
    carts = final["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["items"][0]["item_code"] == "S-MILK"


async def test_never_calls_retailer_cart_mcp_before_a_retailer_is_chosen():
    llm = FakeLLM(ParsedRequestSchema(items=[], budget=250))
    client = FakeSupermarketDataClient({}, {})
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t5"}}

    await app.ainvoke({"raw_message": "Weekly shopping under ₪250"}, config=config)
    result = await app.ainvoke(Command(resume="basic"), config=config)

    assert result.get("retailer_cart_result") is None


async def test_grocery_list_with_real_items_is_unaffected_by_the_new_routing():
    """Regression guard: a normal item + budget request must still go straight to
    resolve_items, not the weekly-shop-profile clarification."""
    llm = FakeLLM(ParsedRequestSchema(items=["milk"], budget=250))
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
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t6"}}

    result = await app.ainvoke({"raw_message": "milk under 250"}, config=config)

    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["reason"] == "retailer_choice"


async def test_grocery_list_with_no_items_and_no_budget_is_unaffected_by_the_new_routing():
    """Regression guard: the new routing only triggers when a budget is present — an
    empty-items request with no budget at all is a separate, pre-existing concern out of
    scope here, and must keep behaving exactly as it did before."""
    llm = FakeLLM(ParsedRequestSchema(items=[]))
    client = FakeSupermarketDataClient({}, {})
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t7"}}

    result = await app.ainvoke({"raw_message": "..."}, config=config)

    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["reason"] == "retailer_choice"
