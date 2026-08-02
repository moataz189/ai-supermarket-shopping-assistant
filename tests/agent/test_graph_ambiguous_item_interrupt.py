from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import FakeLLM, FakeSupermarketDataClient


async def test_ambiguous_item_interrupt_shows_deduped_options_and_availability_breakdown():
    llm = FakeLLM(ParsedRequestSchema(items=["butter"]))
    candidates = {
        ("butter", "shufersal"): [
            {"item_code": "S-TNUVA", "name": "Tnuva", "price": 5.0},
            {"item_code": "S-TARA", "name": "Tara", "price": 5.5},
        ],
        ("butter", "rami_levy"): [
            {"item_code": "R-TNUVA", "name": "Tnuva", "price": 4.8},
            {"item_code": "R-PRES", "name": "President", "price": 6.0},
        ],
        ("Tnuva", "shufersal"): [{"item_code": "S-TNUVA", "name": "Tnuva", "price": 5.0}],
        ("Tnuva", "rami_levy"): [{"item_code": "R-TNUVA", "name": "Tnuva", "price": 4.8}],
    }
    prices = {
        ("shufersal", "S-TNUVA"): {"unit_price": 5.0, "price": 5.0},
        ("rami_levy", "R-TNUVA"): {"unit_price": 4.8, "price": 4.8},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    result = await app.ainvoke({"raw_message": "butter"}, config=config)

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["reason"] == "ambiguous_product"
    option_ids = {opt["id"] for opt in payload["options"]}
    assert option_ids == {"Tnuva", "Tara", "President"}
    assert payload["availability_by_retailer"] == {
        "shufersal": ["Tara", "Tnuva"],
        "rami_levy": ["President", "Tnuva"],
    }

    final = await app.ainvoke(Command(resume="Tnuva"), config=config)

    assert "__interrupt__" in final
    carts = final["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["items"][0]["item_code"] == "S-TNUVA"
    assert carts["rami_levy"]["items"][0]["item_code"] == "R-TNUVA"
