from typing import Literal, TypedDict


class ParsedItem(TypedDict):
    name: str
    quantity: float | None


class ParsedRequest(TypedDict):
    items: list[ParsedItem]
    budget: float | None
    dietary_constraints: list[str]
    retailer_preference: str | None
    brand_preference: str | None
    selection_preference: Literal["cheapest", "no_preference"]


class AgentState(TypedDict, total=False):
    raw_message: str
    parsed_request: ParsedRequest
    item_candidates: dict[str, dict[str, list[dict]]]  # item name -> retailer -> candidates
    resolved_choices: dict[str, str]          # item name -> resolved label
    pending_clarification_item: str | None
    retailer_carts: dict[str, dict]           # "shufersal"/"rami_levy" -> cart dict
    chosen_retailer: str | None
    warnings: list[dict]
    status: Literal["success", "partial_success", "needs_clarification", "awaiting_retailer_choice"]
    clarification: dict | None
    final_result: dict
