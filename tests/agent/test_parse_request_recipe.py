from app.agent.nodes.parse_request import ParsedRequestSchema, make_parse_request
from tests.agent.fakes import FakeLLM


async def test_grocery_list_request_type_defaults_when_llm_omits_it():
    llm = FakeLLM(ParsedRequestSchema(items=["milk"]))
    node = make_parse_request(llm)

    result = await node({"raw_message": "milk"})

    parsed = result["parsed_request"]
    assert parsed["request_type"] == "grocery_list"
    assert parsed["recipe_query"] is None
    assert parsed["servings"] is None
    assert parsed["items"] == [{"name": "milk", "quantity": None}]


async def test_recipe_request_does_not_touch_raw_message_key():
    llm = FakeLLM(
        ParsedRequestSchema(request_type="recipe", recipe_query="שקשוקה", servings=4, items=[])
    )
    node = make_parse_request(llm)

    result = await node({"raw_message": "אני רוצה שקשוקה ל-4"})

    assert "raw_message" not in result


async def test_recipe_request_translates_hebrew_query_to_english():
    llm = FakeLLM(
        ParsedRequestSchema(request_type="recipe", recipe_query="שקשוקה", servings=4, items=[])
    )
    node = make_parse_request(llm)

    result = await node({"raw_message": "אני רוצה שקשוקה ל-4"})

    parsed = result["parsed_request"]
    assert parsed["request_type"] == "recipe"
    assert parsed["recipe_query"] == "shakshuka"
    assert parsed["servings"] == 4
    assert parsed["items"] == []
    assert parsed["language"] == "he"


async def test_recipe_request_translates_hebrew_chicken_pasta_phrase():
    llm = FakeLLM(
        ParsedRequestSchema(request_type="recipe", recipe_query="פסטה עם עוף", items=[])
    )
    node = make_parse_request(llm)

    result = await node({"raw_message": "פסטה עם עוף"})

    assert result["parsed_request"]["recipe_query"] == "chicken pasta"


async def test_recipe_request_translates_arabic_query_to_english():
    llm = FakeLLM(
        ParsedRequestSchema(request_type="recipe", recipe_query="شكشوكة لأربعة أشخاص", items=[])
    )
    node = make_parse_request(llm)

    result = await node({"raw_message": "شكشوكة لأربعة أشخاص"})

    parsed = result["parsed_request"]
    assert parsed["recipe_query"] == "shakshuka"
    assert parsed["language"] == "ar"


async def test_recipe_request_english_query_passes_through_unchanged():
    llm = FakeLLM(
        ParsedRequestSchema(request_type="recipe", recipe_query="shakshuka", servings=4, items=[])
    )
    node = make_parse_request(llm)

    result = await node({"raw_message": "shakshuka for 4 please"})

    parsed = result["parsed_request"]
    assert parsed["recipe_query"] == "shakshuka"
    assert parsed["language"] == "en"


async def test_recipe_request_falls_back_to_raw_message_when_llm_omits_recipe_query():
    llm = FakeLLM(ParsedRequestSchema(request_type="recipe", servings=4, items=[]))
    node = make_parse_request(llm)

    result = await node({"raw_message": "אני רוצה שקשוקה ל-4"})

    assert result["parsed_request"]["recipe_query"] == "shakshuka"
