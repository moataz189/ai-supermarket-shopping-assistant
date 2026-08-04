from typing import Literal, TypedDict


class ParsedItem(TypedDict, total=False):
    name: str
    display_name: str  # localized label; only set for recipe-derived items (CP7)
    quantity: float | None
    unit: str  # only set for recipe-derived items (CP7) — grocery-list items have none


class ParsedRequest(TypedDict):
    request_type: Literal["recipe", "grocery_list"]
    items: list[ParsedItem]
    recipe_query: str | None
    servings: int | None
    language: str  # detected from raw_message, e.g. "en"/"he"/"ar" (CP7)
    budget: float | None
    dietary_constraints: list[str]
    retailer_preference: str | None
    brand_preference: str | None
    selection_preference: Literal["cheapest", "no_preference"]


class RecipeCandidate(TypedDict):
    id: int
    title: str  # canonical English title from Spoonacular — used for internal matching
    display_title: str  # localized/translated title shown to the user


class ChosenRecipe(TypedDict):
    id: int
    title: str
    display_title: str
    servings: int | None


class AgentState(TypedDict, total=False):
    raw_message: str
    parsed_request: ParsedRequest
    recipe_candidates: list[RecipeCandidate]
    recipe_ambiguous: bool
    chosen_recipe_id: int | None
    chosen_recipe: ChosenRecipe | None
    dietary_conflicts: list[str]              # item names with no dietary-compliant option
    item_candidates: dict[str, dict[str, list[dict]]]  # item name -> retailer -> candidates
    resolved_choices: dict[str, str]          # item name -> resolved label
    pending_clarification_item: str | None
    retailer_carts: dict[str, dict]           # "shufersal"/"rami_levy" -> cart dict
    chosen_retailer: str | None
    retailer_cart_result: dict | None         # CP8's prepare_retailer_cart tool result
    warnings: list[dict]
    status: Literal["success", "partial_success", "needs_clarification", "awaiting_retailer_choice"]
    clarification: dict | None
    final_result: dict
