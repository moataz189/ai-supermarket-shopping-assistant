from typing import Literal, TypedDict


class ParsedItem(TypedDict, total=False):
    name: str
    display_name: str  # user-facing label in this conversation's own language; only set
    # for recipe-derived items (CP7)
    search_name: str  # catalog search query — always tried in Hebrew when a translation
    # exists, independent of the conversation's language (the real catalog is Hebrew-only
    # regardless); only set for recipe-derived items (CP9 follow-up)
    english_name: str  # the canonical English ingredient name as returned by Spoonacular
    # — preserved alongside search_name for debugging/future improvements (CP9 follow-up,
    # 2026-08-08: static-dictionary translation); only set for recipe-derived items
    translation_resolved: bool  # whether english_name was found in the static Hebrew
    # ingredient dictionary (app/agent/ingredient_dictionary.py) — False means
    # search_name fell back to english_name unresolved; only set for recipe-derived items
    quantity: float | None
    unit: str  # only set for recipe-derived items (CP7) — grocery-list items have none
    original_quantity: float | None  # the recipe's own original amount before metric
    # normalization (e.g. 14 "ounces") -- internal-only, preserved for debugging;
    # `quantity`/`unit` above are the normalized value used everywhere else. Only set
    # alongside quantity/unit (recipe-derived items).
    original_unit: str


class ParsedRequest(TypedDict):
    request_type: Literal["recipe", "grocery_list", "general_chat"]
    items: list[ParsedItem]
    recipe_query: str | None
    servings: int | None
    language: str  # detected from raw_message, e.g. "en"/"he"/"ar" (CP7)
    budget: float | None
    dietary_constraints: list[str]
    retailer_preference: str | None
    brand_preference: str | None
    selection_preference: Literal["cheapest", "no_preference"]
    reply: str | None  # only meaningful when request_type == "general_chat" (CP10)


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
    resolved_choices: dict[str, dict[str, str]]  # item name -> retailer -> resolved label
    # (CP9 follow-up, 2026-08-08 — previously item name -> a single label shared across
    # every retailer; a retailer's own product name can genuinely differ from another
    # retailer's for "the same" grocery item, so each retailer's own resolution is kept
    # independent — see resolve_items.py/resolve_ambiguity.py/build_retailer_cart.py)
    pending_clarification_item: str | None
    recipe_items: list[ParsedItem]            # CP10: the full scaled recipe ingredient
    # list, exactly as get_recipe_ingredients.py produced it — preserved here even after
    # select_recipe_ingredients.py filters parsed_request["items"] down to only what the
    # user chose to buy, so the original list is never lost. Unset for grocery-list/
    # weekly-shop requests, which never go through ingredient selection at all.
    selected_recipe_items: list[str]          # CP10: names of the recipe_items the user
    # selected to buy — a subset of recipe_items, mirrored into parsed_request["items"]
    # (the list every downstream node — resolve_items, build_retailer_cart — actually
    # consumes) so nothing downstream needs to know ingredient selection exists at all.
    retailer_carts: dict[str, dict]           # "shufersal"/"rami_levy" -> cart dict
    open_ended_budget_selection: bool         # True only when items came from
    # resolve_weekly_shop_profile.py (a budget-only request with no items, or its
    # "custom" freeform follow-up) — tells build_retailer_cart.py to progressively
    # select items that fit `budget * 1.10` instead of adding every item unconditionally.
    # Absent/False for every explicit shopping list (recipe or grocery-list-with-items),
    # which must never have requested items silently dropped for budget reasons.
    chosen_retailer: str | None
    retailer_cart_result: dict | None         # CP8's prepare_retailer_cart tool result
    warnings: list[dict]
    status: Literal["success", "partial_success", "needs_clarification", "awaiting_retailer_choice"]
    clarification: dict | None
    final_result: dict
