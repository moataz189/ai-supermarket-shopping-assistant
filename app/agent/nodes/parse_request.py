from typing import Literal

from pydantic import BaseModel, field_validator

from app.agent.i18n import detect_language, translate_recipe_query
from app.agent.state import AgentState

PARSE_PROMPT = (
    "Classify the user's request as `request_type`: 'recipe' if they're asking to cook or "
    "make a dish, otherwise 'grocery_list'. If 'recipe', fill `recipe_query` with a short "
    "English search phrase naming the dish (translate it to English if the user wrote in "
    "another language) and `servings` if a serving count was stated; leave `items` empty. "
    "If 'grocery_list', extract each grocery/household item as a separate string in `items`, "
    "singular, without quantities, and leave `recipe_query`/`servings` unset. Extract "
    "`budget` (a number, no currency symbol) if stated. Extract `dietary_constraints` as "
    "short tags (e.g. 'no dairy', 'vegan') — a stated 'vegan only'/'gluten-free only' "
    "preference belongs here too. Extract `retailer_preference` ('shufersal' or 'rami_levy') "
    "and `brand_preference` only if explicitly stated. Extract `selection_preference` as "
    "'cheapest' only if the user asked for the cheapest option whenever a choice comes up; "
    "otherwise 'no_preference'."
)


class ParsedRequestSchema(BaseModel):
    request_type: Literal["recipe", "grocery_list"] = "grocery_list"
    items: list[str] = []
    recipe_query: str | None = None
    servings: int | None = None
    budget: float | None = None
    dietary_constraints: list[str] = []
    retailer_preference: str | None = None
    brand_preference: str | None = None
    selection_preference: Literal["cheapest", "no_preference"] = "no_preference"

    @field_validator("recipe_query", "retailer_preference", "brand_preference", mode="before")
    @classmethod
    def _coerce_empty_list_to_none(cls, value):
        # Some Bedrock models' tool-calling output fills an unset optional string field
        # with `[]` instead of omitting it or returning null (observed with
        # openai.gpt-oss-20b-1:0) — a type-compatibility quirk, not a real value.
        if value == []:
            return None
        return value


def make_parse_request(llm):
    structured_llm = llm.with_structured_output(ParsedRequestSchema)

    async def parse_request(state: AgentState) -> AgentState:
        raw_message = state["raw_message"]
        result: ParsedRequestSchema = await structured_llm.ainvoke(
            [("system", PARSE_PROMPT), ("user", raw_message)]
        )

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
        }}

    return parse_request
