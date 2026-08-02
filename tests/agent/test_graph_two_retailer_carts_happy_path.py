from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import FakeLLM, FakeSupermarketDataClient


async def test_two_independent_carts_built_and_happy_path_resumes_with_a_choice():
    llm = FakeLLM(ParsedRequestSchema(items=["milk", "bread"]))
    candidates = {
        ("milk", "shufersal"): [{"item_code": "S-MILK", "name": "Milk 3%", "price": 6.0}],
        ("Milk 3%", "shufersal"): [{"item_code": "S-MILK", "name": "Milk 3%", "price": 6.0}],
        ("milk", "rami_levy"): [{"item_code": "R-MILK", "name": "Milk 3%", "price": 5.5}],
        ("Milk 3%", "rami_levy"): [{"item_code": "R-MILK", "name": "Milk 3%", "price": 5.5}],
        ("bread", "shufersal"): [{"item_code": "S-BREAD", "name": "Bread Whole Wheat", "price": 8.0}],
        ("Bread Whole Wheat", "shufersal"): [
            {"item_code": "S-BREAD", "name": "Bread Whole Wheat", "price": 8.0}
        ],
        ("bread", "rami_levy"): [{"item_code": "R-BREAD", "name": "Bread Whole Wheat", "price": 7.0}],
        ("Bread Whole Wheat", "rami_levy"): [
            {"item_code": "R-BREAD", "name": "Bread Whole Wheat", "price": 7.0}
        ],
    }
    prices = {
        ("shufersal", "S-MILK"): {"unit_price": 6.0, "price": 6.0},
        ("shufersal", "S-BREAD"): {"unit_price": 8.0, "price": 8.0},
        ("rami_levy", "R-MILK"): {"unit_price": 5.5, "price": 5.5},
        ("rami_levy", "R-BREAD"): {"unit_price": 7.0, "price": 7.0},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    result = await app.ainvoke({"raw_message": "milk and bread"}, config=config)

    assert "__interrupt__" in result
    shufersal = result["retailer_carts"]["shufersal"]
    rami_levy = result["retailer_carts"]["rami_levy"]
    assert shufersal["total"] == 14.0
    assert rami_levy["total"] == 12.5
    assert shufersal["missing_items"] == []
    assert rami_levy["missing_items"] == []

    final = await app.ainvoke(Command(resume="shufersal"), config=config)

    assert final["final_result"]["chosen_retailer"] == "shufersal"
    assert final["final_result"]["carts"]["shufersal"]["total"] == 14.0
    assert final["final_result"]["carts"]["rami_levy"]["total"] == 12.5
