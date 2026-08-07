from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import FakeLLM, FakeSupermarketDataClient


async def test_no_savings_badge_when_one_retailer_has_no_matching_products():
    """Reproduces a real, live-reported bug: a zero-total cart (every requested item
    missing) was shown as "Save ₪41.90" cheaper than a real, fully-priced cart — a ₪0.00
    incomplete cart must never be presented as the cheapest option."""
    llm = FakeLLM(ParsedRequestSchema(items=["גלידה"]))
    candidates = {
        ("גלידה", "shufersal"): [{"item_code": "S-ICE", "name": "גלידה", "price": 41.90}],
        # rami_levy never carries this product at all — genuinely empty candidates
    }
    prices = {
        ("shufersal", "S-ICE"): {"unit_price": 41.90, "price": 41.90},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    result = await app.ainvoke({"raw_message": "גלידה"}, config=config)

    assert "__interrupt__" in result
    carts = result["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["total"] == 41.90
    assert carts["rami_levy"]["total"] == 0
    assert carts["rami_levy"]["missing_items"]
    assert carts["shufersal"]["savings_vs_other"] == 0
    assert carts["rami_levy"]["savings_vs_other"] == 0


async def test_savings_badge_shown_when_both_carts_are_real_and_comparable():
    """Regression guard: the normal, both-sides-priced case must still show the real
    savings difference — this isn't about removing the feature, only incomplete carts."""
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
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t2"}}

    result = await app.ainvoke({"raw_message": "milk"}, config=config)

    carts = result["__interrupt__"][0].value["carts"]
    assert carts["rami_levy"]["savings_vs_other"] == 0.5
    assert carts["shufersal"]["savings_vs_other"] == 0


async def test_no_savings_badge_when_both_carts_are_empty():
    llm = FakeLLM(ParsedRequestSchema(items=["nonexistent"]))
    client = FakeSupermarketDataClient({}, {})
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t3"}}

    result = await app.ainvoke({"raw_message": "nonexistent"}, config=config)

    carts = result["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["total"] == 0
    assert carts["rami_levy"]["total"] == 0
    assert carts["shufersal"]["savings_vs_other"] == 0
    assert carts["rami_levy"]["savings_vs_other"] == 0
