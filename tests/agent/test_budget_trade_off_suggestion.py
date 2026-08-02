from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import FakeLLM, FakeSupermarketDataClient


async def test_trade_off_suggestion_only_generated_for_over_budget_retailer():
    llm = FakeLLM(ParsedRequestSchema(items=["olive oil"], budget=25))
    candidates = {
        ("olive oil", "shufersal"): [
            {"item_code": "S-OO1", "name": "Extra Virgin Olive Oil 1L", "price": 20.0}
        ],
        ("olive oil", "rami_levy"): [
            {"item_code": "R-OO1", "name": "Extra Virgin Olive Oil 1L", "price": 35.0},
            {"item_code": "R-OO2", "name": "Extra Virgin Olive Oil 1L", "price": 22.0},
        ],
        ("Extra Virgin Olive Oil 1L", "shufersal"): [
            {"item_code": "S-OO1", "name": "Extra Virgin Olive Oil 1L", "price": 20.0}
        ],
        ("Extra Virgin Olive Oil 1L", "rami_levy"): [
            {"item_code": "R-OO1", "name": "Extra Virgin Olive Oil 1L", "price": 35.0}
        ],
    }
    prices = {
        ("shufersal", "S-OO1"): {"unit_price": 20.0, "price": 20.0},
        ("rami_levy", "R-OO1"): {"unit_price": 35.0, "price": 35.0},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    result = await app.ainvoke({"raw_message": "olive oil, budget 25"}, config=config)

    shufersal = result["retailer_carts"]["shufersal"]
    rami_levy = result["retailer_carts"]["rami_levy"]

    assert shufersal["over_budget_by"] is None
    assert shufersal["trade_off_suggestions"] == []

    assert rami_levy["over_budget_by"] == 10.0
    assert len(rami_levy["trade_off_suggestions"]) == 1
    suggestion = rami_levy["trade_off_suggestions"][0]
    assert suggestion["savings"] == 13.0
    assert suggestion["item_name"] == "olive oil"
