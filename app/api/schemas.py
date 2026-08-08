from pydantic import BaseModel


class ChatRequest(BaseModel):
    thread_id: str | None = None
    message: str


class ClarificationOption(BaseModel):
    id: str
    label: str
    price: float | None = None  # only set for reason == "ambiguous_product" options
    # (options_by_retailer below), so the user can compare candidates before choosing


class RecipeIngredient(BaseModel):
    name: str
    quantity: float | None = None
    unit: str | None = None


class RecipeInfo(BaseModel):
    title: str | None = None
    servings: int | None = None
    ingredients: list[RecipeIngredient]


class Clarification(BaseModel):
    reason: str
    question: str
    options: list[ClarificationOption] = []  # used by "retailer_choice"/"ambiguous_recipe"
    # — a single flat, single-answer choice. Absent/empty for "ambiguous_product", which
    # uses options_by_retailer below instead (CP9 follow-up, 2026-08-08).
    carts: dict | None = None  # populated only when reason == "retailer_choice"
    options_by_retailer: dict[str, list[ClarificationOption]] | None = None  # only when
    # reason == "ambiguous_product" (CP9 follow-up, 2026-08-08 — replaces the old flat
    # options + availability_by_retailer pair) — each retailer's own independent set of
    # candidates (with price), for a retailer that's genuinely ambiguous on its own
    # candidates; a retailer already auto-resolved (exactly one candidate) or with no
    # candidates at all is simply absent here, never asked about. The user picks
    # independently per retailer present — e.g. {"shufersal": [...], "rami_levy": [...]}.
    recipe: RecipeInfo | None = None  # populated only when reason == "retailer_choice"
    # and the original request was a recipe — shown before the user picks so a recipe's
    # requested quantities are visible up front, not just inferable from the final cart.


class CartLine(BaseModel):
    name: str
    item_code: str
    product_name: str
    unit_price: float
    qty: float
    subtotal: float
    link: str | None = None
    # Only set for recipe-derived items — the recipe's actual requested amount (e.g. 400
    # "g"), independent of `qty` above (which stays 1 for this line's own
    # price-comparison subtotal math regardless). None for ordinary grocery-list/
    # weekly-shop items, exactly as before these fields existed.
    requested_quantity: float | None = None
    requested_unit: str | None = None


class RetailerCart(BaseModel):
    retailer: str
    items: list[CartLine]
    missing_items: list[dict]
    total: float
    budget: float | None
    over_budget_by: float | None
    trade_off_suggestions: list[dict]


class RetailerCartItemResult(BaseModel):
    name: str
    item_code: str
    status: str
    reason: str | None = None
    matched_by: str | None = None
    quantity_confirmed: float | None = None
    # Only populated for recipe-derived items (see CartLine above) — requested_* is what
    # the recipe actually asked for; cart_* is what the retailer's own selling-method/
    # increment rules actually resulted in (e.g. "400 g requested" vs "0.5 kg added").
    # None for ordinary grocery-list/weekly-shop items.
    requested_quantity: float | None = None
    requested_unit: str | None = None
    cart_quantity: float | None = None
    cart_unit: str | None = None


class RetailerCartResult(BaseModel):
    retailer: str
    added: list[RetailerCartItemResult]
    failed: list[RetailerCartItemResult]
    blocked: bool
    blocked_reason: str | None = None
    cart_url: str | None = None


class ChatResponse(BaseModel):
    thread_id: str
    status: str
    clarification: Clarification | None = None
    carts: dict[str, RetailerCart] | None = None
    chosen_retailer: str | None = None
    retailer_cart_result: RetailerCartResult | None = None
    warnings: list[dict] = []
    message: str | None = None  # a natural-language reply for general_chat requests
    # Only set for a recipe request — the scaled ingredient list (name/quantity/unit),
    # shown to the user before/alongside the retailer comparison so they can see what the
    # recipe actually requires without inferring it from the final cart.
    recipe: RecipeInfo | None = None
