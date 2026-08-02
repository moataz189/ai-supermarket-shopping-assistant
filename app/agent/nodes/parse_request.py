from typing import Literal

from pydantic import BaseModel

from app.agent.state import AgentState

PARSE_PROMPT = (
    "Extract a structured shopping list from the user's message. List each "
    "grocery/household item as a separate string in `items`, singular, without "
    "quantities. Extract `budget` (a number, no currency symbol) if stated. Extract "
    "`dietary_constraints` as short tags (e.g. 'no dairy', 'vegan') — a stated 'vegan "
    "only'/'gluten-free only' preference belongs here too. Extract `retailer_preference` "
    "('shufersal' or 'rami_levy') and `brand_preference` only if explicitly stated. "
    "Extract `selection_preference` as 'cheapest' only if the user asked for the "
    "cheapest option whenever a choice comes up; otherwise 'no_preference'."
)


class ParsedRequestSchema(BaseModel):
    items: list[str]
    budget: float | None = None
    dietary_constraints: list[str] = []
    retailer_preference: str | None = None
    brand_preference: str | None = None
    selection_preference: Literal["cheapest", "no_preference"] = "no_preference"


def make_parse_request(llm):
    structured_llm = llm.with_structured_output(ParsedRequestSchema)

    async def parse_request(state: AgentState) -> AgentState:
        result: ParsedRequestSchema = await structured_llm.ainvoke(
            [("system", PARSE_PROMPT), ("user", state["raw_message"])]
        )
        return {"parsed_request": {
            "items": [{"name": n, "quantity": None} for n in result.items],
            "budget": result.budget,
            "dietary_constraints": result.dietary_constraints,
            "retailer_preference": result.retailer_preference,
            "brand_preference": result.brand_preference,
            "selection_preference": result.selection_preference,
        }}

    return parse_request
