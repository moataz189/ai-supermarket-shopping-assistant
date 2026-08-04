from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import FakeLLM, FakeRetailerCartClient, FakeSupermarketDataClient


def _milk_candidates_and_prices():
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
    return candidates, prices


async def test_decline_never_calls_retailer_cart_client():
    llm = FakeLLM(ParsedRequestSchema(items=["milk"]))
    candidates, prices = _milk_candidates_and_prices()
    client = FakeSupermarketDataClient(candidates, prices)
    retailer_cart_client = FakeRetailerCartClient({"retailer": "shufersal"})
    app = build_graph(client, llm, MemorySaver(), retailer_cart_client=retailer_cart_client)
    config = {"configurable": {"thread_id": "t1"}}

    await app.ainvoke({"raw_message": "milk"}, config=config)
    final = await app.ainvoke(Command(resume="decline"), config=config)

    assert retailer_cart_client.calls == []
    assert final["final_result"]["retailer_cart_result"] is None


async def test_choosing_a_retailer_invokes_the_client_with_only_that_retailers_items():
    llm = FakeLLM(ParsedRequestSchema(items=["milk"]))
    candidates, prices = _milk_candidates_and_prices()
    client = FakeSupermarketDataClient(candidates, prices)
    canned_result = {
        "retailer": "shufersal",
        "added": [
            {
                "name": "milk",
                "item_code": "S-MILK",
                "status": "added",
                "reason": None,
                "matched_by": "item_code",
                "quantity_confirmed": 1,
            }
        ],
        "failed": [],
        "blocked": False,
        "blocked_reason": None,
        "cart_url": "https://www.shufersal.co.il/online/he/cart",
    }
    retailer_cart_client = FakeRetailerCartClient(canned_result)
    app = build_graph(client, llm, MemorySaver(), retailer_cart_client=retailer_cart_client)
    config = {"configurable": {"thread_id": "t1"}}

    await app.ainvoke({"raw_message": "milk"}, config=config)
    final = await app.ainvoke(Command(resume="shufersal"), config=config)

    assert len(retailer_cart_client.calls) == 1
    called_retailer, called_items = retailer_cart_client.calls[0]
    assert called_retailer == "shufersal"
    assert called_items == [{"name": "milk", "item_code": "S-MILK", "quantity": 1}]
    assert final["final_result"]["retailer_cart_result"] == canned_result


async def test_partial_failure_result_passes_through_unchanged():
    llm = FakeLLM(ParsedRequestSchema(items=["milk"]))
    candidates, prices = _milk_candidates_and_prices()
    client = FakeSupermarketDataClient(candidates, prices)
    partial_result = {
        "retailer": "rami_levy",
        "added": [],
        "failed": [
            {
                "name": "milk",
                "item_code": "R-MILK",
                "status": "error",
                "reason": "skipped_after_block",
                "matched_by": None,
                "quantity_confirmed": None,
            }
        ],
        "blocked": True,
        "blocked_reason": "captcha",
        "cart_url": None,
    }
    retailer_cart_client = FakeRetailerCartClient(partial_result)
    app = build_graph(client, llm, MemorySaver(), retailer_cart_client=retailer_cart_client)
    config = {"configurable": {"thread_id": "t1"}}

    await app.ainvoke({"raw_message": "milk"}, config=config)
    final = await app.ainvoke(Command(resume="rami_levy"), config=config)

    assert final["final_result"]["retailer_cart_result"] == partial_result
