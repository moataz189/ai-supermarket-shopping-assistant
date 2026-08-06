import json
import re
from typing import Literal

from pydantic import BaseModel, field_validator

from app.agent.i18n import detect_language, translate_recipe_query
from app.agent.state import AgentState

PARSE_PROMPT = (
    "You are the request-classification component of an AI supermarket shopping "
    "assistant. The assistant helps users build grocery lists, find recipes, compare "
    "supermarket carts, respect budgets and dietary preferences, and prepare a selected "
    "retailer cart.\n\n"
    "Classify the user's message into exactly one `request_type`:\n"
    "- 'recipe': the user wants to cook, prepare, or find a recipe for a dish.\n"
    "- 'grocery_list': the user wants to buy, compare, search for, or add grocery or "
    "household products.\n"
    "- 'general_chat': greetings, thanks, small talk, questions about the assistant, or "
    "messages that do not contain a shopping or recipe request.\n\n"
    "Do not interpret greetings or conversational words as product names.\n\n"
    "If 'recipe', fill `recipe_query` with a short English search phrase naming the dish "
    "(translate it to English if the user wrote in another language) and `servings` if a "
    "serving count was stated; leave `items` empty.\n"
    "If 'grocery_list', extract each grocery/household item as a separate string in "
    "`items`, singular, without quantities, written in the exact same language and "
    "wording the user used for it — never translate or rephrase an item, since it's "
    "matched against retailer catalog text verbatim, not by meaning. Leave "
    "`recipe_query`/`servings` unset. Extract `budget` (a number, no currency symbol) if "
    "stated. Extract `dietary_constraints` as short tags (e.g. 'no dairy', 'vegan') — a "
    "stated 'vegan only'/'gluten-free only' preference belongs here too. Extract "
    "`retailer_preference` ('shufersal' or 'rami_levy') and `brand_preference` only if "
    "explicitly stated. Extract `selection_preference` as 'cheapest' only if the user "
    "asked for the cheapest option whenever a choice comes up; otherwise 'no_preference'.\n"
    "If 'general_chat', fill `reply` with a brief, natural, friendly response (1-3 "
    "sentences) in the same language the user wrote in, written as the AI supermarket "
    "shopping assistant described above. If they ask who you are or what you can do, "
    "mention that you help with grocery lists, recipes, comparing supermarket prices, "
    "budgets, dietary preferences, and preparing a retailer cart. Leave "
    "`items`/`recipe_query`/`servings` unset."
)


class ParsedRequestSchema(BaseModel):
    request_type: Literal["recipe", "grocery_list", "general_chat"] = "grocery_list"
    items: list[str] = []
    recipe_query: str | None = None
    servings: int | None = None
    budget: float | None = None
    dietary_constraints: list[str] = []
    retailer_preference: str | None = None
    brand_preference: str | None = None
    selection_preference: Literal["cheapest", "no_preference"] = "no_preference"
    reply: str | None = None  # only meaningful when request_type == "general_chat"

    @field_validator(
        "recipe_query", "servings", "budget", "retailer_preference", "brand_preference",
        "reply",
        mode="before",
    )
    @classmethod
    def _coerce_empty_list_to_none(cls, value):
        # Some Bedrock models' tool-calling output fills an unset optional scalar field
        # (string, int, or float) with `[]` instead of omitting it or returning null
        # (observed with openai.gpt-oss-20b-1:0, first for brand_preference, then budget)
        # — a type-compatibility quirk, not a real value. Deliberately excludes `items`/
        # `dietary_constraints` (list[str] fields where `[]` is a legitimate value).
        if value == []:
            return None
        return value


def _extract_json_from_raw_content(content) -> dict:
    """Fallback for when the model answers with plain JSON text instead of a real tool
    call — observed with openai.gpt-oss-20b-1:0 on Bedrock, non-deterministically (the
    same model uses a real tool call for some messages and skips it for others).
    `content` is either a plain string or a Bedrock-style list of content blocks (each
    typically `{"type": "text", "text": "..."}` or `{"type": "reasoning_content", ...}`).
    """
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
    raise ValueError("parse_request: model returned no tool call and no JSON in its text content")


def make_parse_request(llm):
    structured_llm = llm.with_structured_output(ParsedRequestSchema, include_raw=True)

    async def parse_request(state: AgentState) -> AgentState:
        raw_message = state["raw_message"]
        output = await structured_llm.ainvoke(
            [("system", PARSE_PROMPT), ("user", raw_message)]
        )
        result: ParsedRequestSchema | None = output["parsed"]
        if result is None:
            result = ParsedRequestSchema(**_extract_json_from_raw_content(output["raw"].content))

        recipe_query = None
        if result.request_type == "recipe":
            recipe_query = translate_recipe_query(result.recipe_query or raw_message)

        return {"parsed_request": {
            "request_type": result.request_type,
            "items": [{"name": n, "quantity": None} for n in result.items],
            "recipe_query": recipe_query,
            "servings": result.servings,
            "language": detect_language(raw_message),
            "budget": result.budget,
            "dietary_constraints": result.dietary_constraints,
            "retailer_preference": result.retailer_preference,
            "brand_preference": result.brand_preference,
            "selection_preference": result.selection_preference,
            "reply": result.reply,
        }}

    return parse_request
