from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import FakeLLM, FakeSupermarketDataClient


async def test_dietary_substitute_used_instead_of_original_when_available():
    llm = FakeLLM(ParsedRequestSchema(items=["milk"], dietary_constraints=["no dairy"]))
    candidates = {
        ("milk", "shufersal"): [{"item_code": "S-MILK", "name": "Tnuva Milk 3%", "price": 6.0}],
        ("milk", "rami_levy"): [{"item_code": "R-MILK", "name": "Tnuva Milk 3%", "price": 5.5}],
        ("oat milk", "shufersal"): [
            {"item_code": "S-OAT", "name": "Oatly Oat Drink", "price": 9.0}
        ],
        ("oat milk", "rami_levy"): [
            {"item_code": "R-OAT", "name": "Oatly Oat Drink", "price": 8.5}
        ],
        ("Oatly Oat Drink", "shufersal"): [
            {"item_code": "S-OAT", "name": "Oatly Oat Drink", "price": 9.0}
        ],
        ("Oatly Oat Drink", "rami_levy"): [
            {"item_code": "R-OAT", "name": "Oatly Oat Drink", "price": 8.5}
        ],
    }
    prices = {
        ("shufersal", "S-OAT"): {"unit_price": 9.0, "price": 9.0},
        ("rami_levy", "R-OAT"): {"unit_price": 8.5, "price": 8.5},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    result = await app.ainvoke({"raw_message": "milk, no dairy"}, config=config)

    shufersal = result["retailer_carts"]["shufersal"]
    rami_levy = result["retailer_carts"]["rami_levy"]

    assert shufersal["missing_items"] == []
    assert rami_levy["missing_items"] == []
    assert shufersal["items"][0]["product_name"] == "Oatly Oat Drink"
    assert rami_levy["items"][0]["product_name"] == "Oatly Oat Drink"
    assert shufersal["items"][0]["item_code"] == "S-OAT"
    assert rami_levy["items"][0]["item_code"] == "R-OAT"


async def test_dietary_conflict_reported_when_no_substitute_mapping_exists():
    llm = FakeLLM(ParsedRequestSchema(items=["chicken"], dietary_constraints=["vegetarian"]))
    candidates = {
        ("chicken", "shufersal"): [
            {"item_code": "S-CHKN", "name": "Chicken Breast", "price": 20.0}
        ],
        ("chicken", "rami_levy"): [
            {"item_code": "R-CHKN", "name": "Chicken Breast", "price": 18.0}
        ],
    }
    prices = {
        ("shufersal", "S-CHKN"): {"unit_price": 20.0, "price": 20.0},
        ("rami_levy", "R-CHKN"): {"unit_price": 18.0, "price": 18.0},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t2"}}

    result = await app.ainvoke({"raw_message": "chicken, vegetarian"}, config=config)

    shufersal = result["retailer_carts"]["shufersal"]
    rami_levy = result["retailer_carts"]["rami_levy"]

    assert shufersal["items"] == []
    assert rami_levy["items"] == []
    assert shufersal["missing_items"] == [{"name": "chicken", "reason": "dietary_conflict"}]
    assert rami_levy["missing_items"] == [{"name": "chicken", "reason": "dietary_conflict"}]


async def test_no_dietary_constraints_behaves_exactly_like_cp4():
    llm = FakeLLM(ParsedRequestSchema(items=["milk"]))
    candidates = {
        ("milk", "shufersal"): [{"item_code": "S-MILK", "name": "Tnuva Milk 3%", "price": 6.0}],
        ("Tnuva Milk 3%", "shufersal"): [
            {"item_code": "S-MILK", "name": "Tnuva Milk 3%", "price": 6.0}
        ],
        ("milk", "rami_levy"): [{"item_code": "R-MILK", "name": "Tnuva Milk 3%", "price": 5.5}],
        ("Tnuva Milk 3%", "rami_levy"): [
            {"item_code": "R-MILK", "name": "Tnuva Milk 3%", "price": 5.5}
        ],
    }
    prices = {
        ("shufersal", "S-MILK"): {"unit_price": 6.0, "price": 6.0},
        ("rami_levy", "R-MILK"): {"unit_price": 5.5, "price": 5.5},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t3"}}

    result = await app.ainvoke({"raw_message": "milk"}, config=config)

    shufersal = result["retailer_carts"]["shufersal"]
    assert shufersal["items"][0]["product_name"] == "Tnuva Milk 3%"
    assert shufersal["missing_items"] == []
