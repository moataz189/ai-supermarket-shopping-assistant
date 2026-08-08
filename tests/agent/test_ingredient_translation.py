from app.agent.ingredient_translation import (
    IngredientTranslationItem,
    IngredientTranslationSchema,
    translate_ingredients_to_hebrew,
)
from tests.agent.fakes import FakeLLM


async def test_empty_names_never_calls_the_llm():
    llm = FakeLLM(parsed=IngredientTranslationSchema(translations=[]))
    result = await translate_ingredients_to_hebrew(llm, [])
    assert result == {}


async def test_translates_a_batch_in_one_call():
    llm = FakeLLM(parsed=IngredientTranslationSchema(translations=[
        IngredientTranslationItem(original_name="pasta", search_name_he="פסטה"),
        IngredientTranslationItem(original_name="garlic", search_name_he="שום"),
    ]))

    result = await translate_ingredients_to_hebrew(llm, ["pasta", "garlic"])

    assert result == {"pasta": "פסטה", "garlic": "שום"}


async def test_partial_response_still_returns_what_it_got():
    llm = FakeLLM(parsed=IngredientTranslationSchema(translations=[
        IngredientTranslationItem(original_name="pasta", search_name_he="פסטה"),
    ]))

    result = await translate_ingredients_to_hebrew(llm, ["pasta", "an unmapped thing"])

    assert result == {"pasta": "פסטה"}


async def test_falls_back_to_raw_content_json_when_no_tool_call():
    raw_json = '{"translations": [{"original_name": "pasta", "search_name_he": "פסטה"}]}'
    llm = FakeLLM(parsed=None, raw_content=raw_json)

    result = await translate_ingredients_to_hebrew(llm, ["pasta"])

    assert result == {"pasta": "פסטה"}


async def test_never_raises_on_llm_failure():
    class BoomLLM:
        def with_structured_output(self, schema, include_raw=False):
            return self

        async def ainvoke(self, messages):
            raise RuntimeError("bedrock is down")

    result = await translate_ingredients_to_hebrew(BoomLLM(), ["pasta"])

    assert result == {}


async def test_never_raises_on_unparseable_raw_content():
    llm = FakeLLM(parsed=None, raw_content="not json at all")

    result = await translate_ingredients_to_hebrew(llm, ["pasta"])

    assert result == {}


async def test_empty_search_name_from_model_is_dropped():
    llm = FakeLLM(parsed=IngredientTranslationSchema(translations=[
        IngredientTranslationItem(original_name="pasta", search_name_he=""),
    ]))

    result = await translate_ingredients_to_hebrew(llm, ["pasta"])

    assert result == {}
