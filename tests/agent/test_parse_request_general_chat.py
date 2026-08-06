from app.agent.nodes.parse_request import ParsedRequestSchema, make_parse_request
from tests.agent.fakes import FakeLLM


async def test_general_chat_request_carries_reply_and_no_items():
    llm = FakeLLM(
        ParsedRequestSchema(request_type="general_chat", reply="Hi! How can I help you shop today?")
    )
    node = make_parse_request(llm)

    result = await node({"raw_message": "hi"})

    parsed = result["parsed_request"]
    assert parsed["request_type"] == "general_chat"
    assert parsed["reply"] == "Hi! How can I help you shop today?"
    assert parsed["items"] == []
    assert parsed["recipe_query"] is None
    assert parsed["servings"] is None


async def test_general_chat_reply_is_none_when_llm_omits_it():
    llm = FakeLLM(ParsedRequestSchema(request_type="general_chat"))
    node = make_parse_request(llm)

    result = await node({"raw_message": "hey"})

    assert result["parsed_request"]["reply"] is None


async def test_general_chat_does_not_touch_raw_message_key():
    llm = FakeLLM(ParsedRequestSchema(request_type="general_chat", reply="Hey there!"))
    node = make_parse_request(llm)

    result = await node({"raw_message": "hey"})

    assert "raw_message" not in result
