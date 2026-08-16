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
    id: int | None = None  # the Spoonacular recipe id -- lets the frontend later fetch
    # this exact recipe's cooking instructions via POST /recipe-instructions, without
    # resuming this conversation's LangGraph thread (see app/api/routes/recipe.py).
    title: str | None = None
    servings: int | None = None
    ingredients: list[RecipeIngredient]


class IngredientSelectionOption(BaseModel):
    """One row on the recipe ingredient-selection screen (CP10) — a checkbox with a
    quantity/unit, not just a label. `id` and `name` are always the same value today
    (the ingredient's own stable name), kept as two separate fields to match the wire
    contract explicitly rather than overload `name` as both identity and display data."""

    id: str
    name: str
    display_name: str
    quantity: float | None = None
    unit: str | None = None
    selected: bool


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
    ingredients: list[IngredientSelectionOption] | None = None  # only when reason ==
    # "recipe_ingredient_selection" (CP10) — the full scaled recipe ingredient list, each
    # pre-selected (spec: pressing Continue with no changes should buy everything). The
    # resume answer is the list of selected ids, sent explicitly rather than encoded in
    # free text (app/api/routes/chat.py's _resume_value already recognizes a JSON array).
    recipe: RecipeInfo | None = None  # populated when reason == "retailer_choice" (shown
    # before the user picks a retailer so a recipe's requested quantities are visible up
    # front, not just inferable from the final cart) or reason ==
    # "recipe_ingredient_selection" (CP10 — the header above the ingredient checkboxes,
    # title/servings/full ingredient list); None for any other reason or a non-recipe
    # request.


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
    # Best-effort "how many whole packages will this likely need" estimate (see
    # app/agent/quantity.py) -- set only when the matched product's own package size is
    # known and comparable to requested_quantity/requested_unit. `subtotal` above
    # already reflects this many packages' price when set. None when unknown/not
    # applicable, in which case the frontend falls back to showing requested_quantity/
    # requested_unit directly, exactly as before this field existed.
    estimated_package_count: int | None = None


class RetailerCart(BaseModel):
    retailer: str
    items: list[CartLine]
    missing_items: list[dict]
    total: float
    budget: float | None
    allowed_max: float | None = None  # budget * 1.10; None when no budget was given
    over_budget_by: float | None
    no_items_fit_budget: bool = False  # True only for an open-ended/weekly-profile cart
    # where no candidate item could fit within allowed_max at all — the frontend must
    # never render this as a plain "successful" ₪0.00 cart.
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


class RecipeInstructionsRequest(BaseModel):
    recipe_id: int


class RecipeInstructionStep(BaseModel):
    number: int
    step: str


class RecipeInstructionsResponse(BaseModel):
    recipe_id: int
    instructions: str | None = None
    steps: list[RecipeInstructionStep] | None = None


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
