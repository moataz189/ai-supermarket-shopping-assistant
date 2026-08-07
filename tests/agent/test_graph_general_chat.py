from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_graph
from app.agent.nodes.general_chat import _DEFAULT_REPLY
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import FakeLLM, FakeSupermarketDataClient


async def test_greeting_short_circuits_to_a_reply_without_entering_grocery_pipeline():
    llm = FakeLLM(ParsedRequestSchema(request_type="general_chat", reply="Hi there!"))
    client = FakeSupermarketDataClient({}, {})
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    result = await app.ainvoke({"raw_message": "hi"}, config=config)

    assert "__interrupt__" not in result
    assert result["status"] == "success"
    assert result["warnings"] == []
    assert result["final_result"]["message"] == "Hi there!"
    assert result["final_result"]["carts"] == {}
    assert result["final_result"]["chosen_retailer"] is None
    assert result["final_result"]["retailer_cart_result"] is None
    # never resolved anything against the supermarket data client — "hi" was never
    # treated as a product name
    assert "item_candidates" not in result or result["item_candidates"] == {}


async def test_general_chat_falls_back_to_default_reply_when_llm_omits_one():
    llm = FakeLLM(ParsedRequestSchema(request_type="general_chat"))
    client = FakeSupermarketDataClient({}, {})
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t2"}}

    result = await app.ainvoke({"raw_message": "hey"}, config=config)

    assert result["final_result"]["message"] == _DEFAULT_REPLY
