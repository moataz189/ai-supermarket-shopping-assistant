from app.agent.nodes.parse_request import make_parse_request
from tests.agent.fakes import FakeLLM


async def test_falls_back_to_json_in_text_content_when_model_skips_tool_call():
    """Reproduces a live crash: openai.gpt-oss-20b-1:0 sometimes answers with plain JSON
    text in a 'text' content block instead of a real Bedrock Converse tool call — observed
    live for "I want to make pizza" (worked moments earlier for "shakshuka" with a real
    tool call). `with_structured_output` then returns `parsed=None` with no error, and the
    node crashed with `AttributeError: 'NoneType' object has no attribute 'request_type'`.
    """
    raw_content = [
        {"type": "reasoning_content", "reasoning_content": {"text": "thinking...", "signature": ""}},
        {"type": "text", "text": '{"request_type":"recipe","recipe_query":"pizza"}'},
    ]
    llm = FakeLLM(parsed=None, raw_content=raw_content)
    node = make_parse_request(llm)

    result = await node({"raw_message": "I want to make pizza"})

    parsed = result["parsed_request"]
    assert parsed["request_type"] == "recipe"
    assert parsed["recipe_query"] == "pizza"
    assert parsed["items"] == []


async def test_falls_back_when_content_is_a_plain_json_string():
    llm = FakeLLM(parsed=None, raw_content='{"request_type":"grocery_list","items":["milk"]}')
    node = make_parse_request(llm)

    result = await node({"raw_message": "milk"})

    parsed = result["parsed_request"]
    assert parsed["request_type"] == "grocery_list"
    assert parsed["items"] == [{"name": "milk", "quantity": None}]


async def test_uses_tool_call_result_directly_when_present_no_fallback_needed():
    """Regression guard: the normal (tool-call-succeeded) path must stay unaffected by
    the fallback logic — raw_content is deliberately unparseable garbage here to prove
    the fallback path is never even consulted when `parsed` is already set."""
    from app.agent.nodes.parse_request import ParsedRequestSchema

    llm = FakeLLM(
        parsed=ParsedRequestSchema(request_type="grocery_list", items=["bread"]),
        raw_content="not valid json at all",
    )
    node = make_parse_request(llm)

    result = await node({"raw_message": "bread"})

    assert result["parsed_request"]["items"] == [{"name": "bread", "quantity": None}]
