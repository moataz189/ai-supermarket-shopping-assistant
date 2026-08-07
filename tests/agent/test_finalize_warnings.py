from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import FakeLLM, FakeSupermarketDataClient


async def test_warnings_are_scoped_to_the_chosen_retailer_only():
    """Reproduces a real, live-reported bug: after choosing Shufersal, the conversation
    still ended with a `product_not_found` warning about Rami Levy — no longer relevant
    once the user has committed to a specific retailer."""
    llm = FakeLLM(ParsedRequestSchema(items=["גלידה"]))
    candidates = {
        ("גלידה", "shufersal"): [{"item_code": "S-ICE", "name": "גלידה", "price": 41.90}],
        # rami_levy never carries this product — genuinely missing there
    }
    prices = {
        ("shufersal", "S-ICE"): {"unit_price": 41.90, "price": 41.90},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    await app.ainvoke({"raw_message": "גלידה"}, config=config)
    final = await app.ainvoke(Command(resume="shufersal"), config=config)

    assert final["final_result"]["chosen_retailer"] == "shufersal"
    warning_retailers = {w["retailer"] for w in final["warnings"]}
    assert warning_retailers == set()  # shufersal itself had no missing items


async def test_declining_keeps_warnings_for_both_retailers():
    """Regression guard: when the user declines to pick a retailer ("just show me
    this"), both retailers' warnings are still relevant and must not be dropped."""
    llm = FakeLLM(ParsedRequestSchema(items=["גלידה"]))
    candidates = {
        ("גלידה", "shufersal"): [{"item_code": "S-ICE", "name": "גלידה", "price": 41.90}],
    }
    prices = {
        ("shufersal", "S-ICE"): {"unit_price": 41.90, "price": 41.90},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t2"}}

    await app.ainvoke({"raw_message": "גלידה"}, config=config)
    final = await app.ainvoke(Command(resume="decline"), config=config)

    assert final["final_result"]["chosen_retailer"] is None
    warning_retailers = {w["retailer"] for w in final["warnings"]}
    assert warning_retailers == {"rami_levy"}


async def test_choosing_the_retailer_with_the_missing_item_still_reports_it():
    """The filter is about *relevance to the chosen retailer*, not about hiding all bad
    news — a missing item on the retailer the user actually picked must still surface."""
    llm = FakeLLM(ParsedRequestSchema(items=["גלידה"]))
    candidates = {
        ("גלידה", "shufersal"): [{"item_code": "S-ICE", "name": "גלידה", "price": 41.90}],
    }
    prices = {
        ("shufersal", "S-ICE"): {"unit_price": 41.90, "price": 41.90},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t3"}}

    await app.ainvoke({"raw_message": "גלידה"}, config=config)
    final = await app.ainvoke(Command(resume="rami_levy"), config=config)

    assert final["final_result"]["chosen_retailer"] == "rami_levy"
    warning_retailers = {w["retailer"] for w in final["warnings"]}
    assert warning_retailers == {"rami_levy"}
