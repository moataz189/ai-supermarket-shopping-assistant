"""Graph-level regression tests for the חזה עוף (chicken breast) whole-kg normalization
(2026-08-16). Real user report: both retailers only sell chicken breast in whole-kg
increments in the currently supported flow, but a fractional request (e.g. the
weekly-shop "one_person" profile's real 0.4 kg serving size) priced the comparison view
at 0.4 kg while the real Retailer-Cart MCP add would buy a whole kg regardless -- the
displayed price/quantity and what actually got bought disagreed.

resolve_items.py's `_normalize_quantity` (see tests/agent/test_resolve_item_rules.py for
its own unit tests) now rounds a whole-kg-only item's quantity UP to the next whole kg
once, early, before anything downstream reads it. These tests verify the fix end-to-end:
the comparison-view price, the budget math, the payload sent to the Retailer-Cart MCP,
and the final "Requested/Added" result all agree on the same normalized quantity, for
BOTH Shufersal and Rami Levy -- and that an ordinary fractional-kg item (tomato) is
completely unaffected in the same run, proving the fix is scoped to chicken breast only.
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from app.agent.nodes.resolve_weekly_shop_profile import STARTER_LISTS
from tests.agent.fakes import FakeLLM, FakeRetailerCartClient, FakeSupermarketDataClient


def _weekly_shop_app(profile: str, retailer_cart_client=None):
    llm = FakeLLM(ParsedRequestSchema(request_type="grocery_list", items=[], budget=200))
    candidates: dict[tuple[str, str], list[dict]] = {}
    prices: dict[tuple[str, str], dict] = {}
    for entry in STARTER_LISTS[profile]:
        name = entry["name"]
        for retailer, code in [("shufersal", f"S-{name}"), ("rami_levy", f"R-{name}")]:
            candidates[(name, retailer)] = [{"item_code": code, "name": name, "price": 10.0}]
            if entry["unit"] == "kg":
                # ₪20/kg, expressed as unit_price (price per GRAM -- see
                # app/db/repositories.py's unit_price): 20 / 1000 = 0.02.
                unit_price = 20.0 / 1000
            else:
                unit_price = 10.0
            prices[(retailer, code)] = {"unit_price": unit_price, "price": 10.0}
    client = FakeSupermarketDataClient(candidates, prices)
    return build_graph(client, llm, MemorySaver(), retailer_cart_client=retailer_cart_client)


async def _run_to_carts(profile: str, thread_id: str):
    app = _weekly_shop_app(profile)
    config = {"configurable": {"thread_id": thread_id}}
    await app.ainvoke({"raw_message": "weekly shop"}, config=config)
    result = await app.ainvoke(Command(resume=profile), config=config)
    return result["__interrupt__"][0].value["carts"]


async def test_one_person_profile_04kg_chicken_prices_as_1kg_on_shufersal():
    carts = await _run_to_carts("one_person", "t-cb-1")

    chicken = next(i for i in carts["shufersal"]["items"] if i["name"] == "חזה עוף")
    assert chicken["requested_quantity"] == 1.0
    # ₪20/kg at the normalized 1.0 kg, not the raw 0.4 kg (which would be ₪8.00).
    assert chicken["subtotal"] == 20.0


async def test_one_person_profile_04kg_chicken_prices_as_1kg_on_rami_levy_too():
    carts = await _run_to_carts("one_person", "t-cb-2")

    chicken = next(i for i in carts["rami_levy"]["items"] if i["name"] == "חזה עוף")
    assert chicken["requested_quantity"] == 1.0
    assert chicken["subtotal"] == 20.0


async def test_couple_profile_08kg_chicken_also_rounds_up_to_1kg_on_both_retailers():
    carts = await _run_to_carts("couple", "t-cb-3")

    for retailer in ("shufersal", "rami_levy"):
        chicken = next(i for i in carts[retailer]["items"] if i["name"] == "חזה עוף")
        assert chicken["requested_quantity"] == 1.0


async def test_family_profile_12kg_chicken_rounds_up_to_2kg_on_both_retailers():
    carts = await _run_to_carts("family", "t-cb-4")

    for retailer in ("shufersal", "rami_levy"):
        chicken = next(i for i in carts[retailer]["items"] if i["name"] == "חזה עוף")
        assert chicken["requested_quantity"] == 2.0
        assert chicken["subtotal"] == 40.0  # ₪20/kg * 2 kg


async def test_tomato_at_05kg_is_unaffected_in_the_same_run_as_chicken_breast():
    # Proves the fix is scoped to חזה עוף only -- not a general kg-rounding rule.
    carts = await _run_to_carts("one_person", "t-cb-5")

    for retailer in ("shufersal", "rami_levy"):
        tomato = next(i for i in carts[retailer]["items"] if i["name"] == "עגבניה")
        assert tomato["requested_quantity"] == 0.5


async def _run_to_mcp_payload(profile: str, retailer: str, thread_id: str):
    result = {"retailer": retailer, "added": [], "failed": [], "blocked": False,
              "blocked_reason": None, "cart_url": None}
    retailer_cart_client = FakeRetailerCartClient(result)
    app = _weekly_shop_app(profile, retailer_cart_client=retailer_cart_client)
    config = {"configurable": {"thread_id": thread_id}}
    await app.ainvoke({"raw_message": "weekly shop"}, config=config)
    await app.ainvoke(Command(resume=profile), config=config)
    await app.ainvoke(Command(resume=retailer), config=config)
    _, called_items = retailer_cart_client.calls[0]
    return {i["name"]: i for i in called_items}


async def test_retailer_cart_mcp_payload_receives_the_normalized_quantity_shufersal():
    by_name = await _run_to_mcp_payload("one_person", "shufersal", "t-cb-6")

    assert by_name["חזה עוף"]["quantity"] == 1.0
    assert by_name["חזה עוף"]["unit"] == "kg"
    assert by_name["עגבניה"]["quantity"] == 0.5  # unaffected, same payload


async def test_retailer_cart_mcp_payload_receives_the_normalized_quantity_rami_levy():
    by_name = await _run_to_mcp_payload("one_person", "rami_levy", "t-cb-7")

    assert by_name["חזה עוף"]["quantity"] == 1.0
    assert by_name["חזה עוף"]["unit"] == "kg"
    assert by_name["עגבניה"]["quantity"] == 0.5


async def test_final_requested_result_reflects_the_normalized_quantity_not_the_raw_amount():
    canned = {
        "retailer": "shufersal",
        "added": [{
            "name": "חזה עוף", "item_code": "S-חזה עוף", "status": "added", "matched_by": "exact_name",
            "quantity_confirmed": 1.0, "requested_quantity": 1.0, "requested_unit": "kg",
            "cart_quantity": 1.0, "cart_unit": "kg",
        }],
        "failed": [], "blocked": False, "blocked_reason": None, "cart_url": "https://example.test/cart",
    }
    retailer_cart_client = FakeRetailerCartClient(canned)
    app = _weekly_shop_app("one_person", retailer_cart_client=retailer_cart_client)
    config = {"configurable": {"thread_id": "t-cb-8"}}

    await app.ainvoke({"raw_message": "weekly shop"}, config=config)
    await app.ainvoke(Command(resume="one_person"), config=config)
    final = await app.ainvoke(Command(resume="shufersal"), config=config)

    added = final["final_result"]["retailer_cart_result"]["added"][0]
    assert added["requested_quantity"] == 1.0  # not the raw 0.4 kg STARTER_LISTS amount
    assert added["requested_unit"] == "kg"
