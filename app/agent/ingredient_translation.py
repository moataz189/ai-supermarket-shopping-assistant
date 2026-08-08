import json
import re

from pydantic import BaseModel

TRANSLATE_PROMPT = (
    "You translate English grocery-ingredient names into the Hebrew term as it would "
    "appear on a real Israeli supermarket product label. For each ingredient given, "
    "return the generic, singular Hebrew grocery term for it — not a specific brand, not "
    "a package size, and not the plural form (Israeli retail catalogs list fresh produce "
    "and staples in singular generic form, e.g. English 'tomato'/'tomatoes' -> Hebrew "
    "'עגבניה', never the plural 'עגבניות'). If an ingredient has no sensible single "
    "grocery-product translation (e.g. a technique or a vague seasoning blend), return "
    "your best generic guess at the closest real product term rather than leaving it out."
)


class IngredientTranslationItem(BaseModel):
    original_name: str
    search_name_he: str


class IngredientTranslationSchema(BaseModel):
    translations: list[IngredientTranslationItem]


def _extract_json_from_raw_content(content) -> dict:
    """Fallback for when the model answers with plain JSON text instead of a real tool
    call — same Bedrock quirk documented in parse_request.py's own copy of this helper."""
    blocks = content if isinstance(content, list) else [content]
    for block in blocks:
        text = block.get("text") if isinstance(block, dict) else block
        if not isinstance(text, str):
            continue
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            continue
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
    raise ValueError("ingredient_translation: model returned no tool call and no JSON in its text content")


async def translate_ingredients_to_hebrew(llm, names: list[str]) -> dict[str, str]:
    """Translates a batch of English ingredient names to Hebrew catalog search terms in
    a single LLM call — used only as a fallback for names the persistent cache
    (app/db/repositories.py's IngredientTranslationRepository) has never seen before, per
    explicit product decision: the LLM is not the primary translation mechanism.

    Never raises: any LLM/parsing failure yields an empty dict, so a translation that
    couldn't be produced just means that ingredient's catalog search falls back to its
    own English name (an ordinary missing_items result), not a broken flow. Only
    successfully-translated names appear in the returned dict — a partial LLM response
    (some names covered, some not) is still useful, not discarded wholesale.
    """
    if not names:
        return {}

    structured_llm = llm.with_structured_output(IngredientTranslationSchema, include_raw=True)
    try:
        output = await structured_llm.ainvoke([
            ("system", TRANSLATE_PROMPT),
            ("user", json.dumps(names, ensure_ascii=False)),
        ])
        result: IngredientTranslationSchema | None = output["parsed"]
        if result is None:
            result = IngredientTranslationSchema(**_extract_json_from_raw_content(output["raw"].content))
    except Exception:
        return {}

    return {item.original_name: item.search_name_he for item in result.translations if item.search_name_he}
