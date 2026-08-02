from pydantic import BaseModel


class ChatRequest(BaseModel):
    thread_id: str | None = None
    message: str


class ClarificationOption(BaseModel):
    id: str
    label: str


class Clarification(BaseModel):
    reason: str
    question: str
    options: list[ClarificationOption]
    carts: dict | None = None  # populated only when reason == "retailer_choice"
    availability_by_retailer: dict[str, list[str]] | None = None  # only when
    # reason == "ambiguous_product" (CP4/CP7) — e.g. {"shufersal": ["Tara", "Tnuva"],
    # "rami_levy": ["President", "Tnuva"]}, so the UI can show which retailer carries
    # which option before the user picks.


class CartLine(BaseModel):
    name: str
    item_code: str
    product_name: str
    unit_price: float
    qty: float
    subtotal: float
    link: str | None = None


class RetailerCart(BaseModel):
    retailer: str
    items: list[CartLine]
    missing_items: list[dict]
    total: float
    budget: float | None
    over_budget_by: float | None
    trade_off_suggestions: list[dict]


class ChatResponse(BaseModel):
    thread_id: str
    status: str
    clarification: Clarification | None = None
    carts: dict[str, RetailerCart] | None = None
    chosen_retailer: str | None = None
    warnings: list[dict] = []
