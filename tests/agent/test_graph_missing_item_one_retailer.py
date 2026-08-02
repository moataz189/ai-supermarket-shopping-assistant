from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import FakeLLM, FakeSupermarketDataClient


async def test_item_missing_at_one_retailer_does_not_affect_the_other():
    llm = FakeLLM(ParsedRequestSchema(items=["kiwi"]))
    candidates = {
        ("kiwi", "shufersal"): [{"item_code": "S-KIWI", "name": "Kiwi", "price": 3.0}],
        ("kiwi", "rami_levy"): [],
        ("Kiwi", "shufersal"): [{"item_code": "S-KIWI", "name": "Kiwi", "price": 3.0}],
        ("Kiwi", "rami_levy"): [],
    }
    prices = {
        ("shufersal", "S-KIWI"): {"unit_price": 3.0, "price": 3.0},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    result = await app.ainvoke({"raw_message": "kiwi"}, config=config)

    assert "__interrupt__" in result
    shufersal = result["retailer_carts"]["shufersal"]
    rami_levy = result["retailer_carts"]["rami_levy"]

    assert shufersal["missing_items"] == []
    assert shufersal["items"][0]["item_code"] == "S-KIWI"

    assert rami_levy["items"] == []
    assert rami_levy["missing_items"] == [{"name": "kiwi", "reason": "not_found"}]
