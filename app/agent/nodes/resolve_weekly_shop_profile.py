from langgraph.types import interrupt

from app.agent.state import AgentState

# Deterministic starter lists, in Hebrew — real Shufersal/Rami Levy catalog data is
# Hebrew-only (retailer feeds have no English product names at all), so an English generic
# term like "tomatoes" never matches a real catalog entry even when the equivalent product
# genuinely exists (e.g. "עגבניה"), confirmed live: every item showed up as missing despite
# real matches being available. Also confirmed live: search_candidates matches by substring
# (`name.ilike(f"%{query}%")`, see app/db/repositories.py) against the stored product name,
# and Israeli retail feeds list fresh produce in singular generic form ("עגבניה", not
# "עגבניות") — a plural query is a different string, not a substring, and silently misses
# too. Item names still flow through the exact same resolve_items/build_*_cart path as a
# normal grocery list, so any of these that still don't match a given retailer's actual
# catalog (real feeds vary store to store) surface as an ordinary missing_items entry, not
# a crash.
#
# Each entry also carries a real quantity/unit — sized per profile's household (e.g.
# "one_person" gets 0.5 kg tomatoes, "family" gets 1 kg), following a real user report that
# every profile silently got the same "1" regardless of household size. These flow through
# the exact same requested_quantity/requested_unit path as a recipe's ingredients (see
# build_retailer_cart.py / mcp_servers/retailer_cart_mcp/quantity.py) — a retailer-specific
# increment/selling-method conversion happens later, at the Retailer-Cart MCP layer, not
# here. Weight/volume items (produce, meat, fish) are in kg; items normally sold as one
# fixed retail package (bread, milk, rice, pasta, cheese...) use a plain unit count instead
# of an invented weight, since there's no deterministic per-product package size to convert
# a weight into a package count with (same reasoning as the recipe flow's "buy one whole
# package" default — see quantity.py's module docstring).
STARTER_LISTS: dict[str, list[dict]] = {
    "basic": [
        {"name": "לחם", "quantity": 1, "unit": "unit"},
        {"name": "חלב", "quantity": 1, "unit": "unit"},
        {"name": "ביצים", "quantity": 1, "unit": "unit"},
        {"name": "אורז", "quantity": 1, "unit": "unit"},
        {"name": "פסטה", "quantity": 1, "unit": "unit"},
        {"name": "שמן זית", "quantity": 1, "unit": "unit"},
        {"name": "עגבניה", "quantity": 0.5, "unit": "kg"},
        {"name": "בצל", "quantity": 0.5, "unit": "kg"},
    ],
    "one_person": [
        {"name": "לחם", "quantity": 1, "unit": "unit"},
        {"name": "חלב", "quantity": 1, "unit": "unit"},
        {"name": "ביצים", "quantity": 1, "unit": "unit"},
        {"name": "חזה עוף", "quantity": 0.4, "unit": "kg"},
        {"name": "אורז", "quantity": 1, "unit": "unit"},
        {"name": "פסטה", "quantity": 1, "unit": "unit"},
        {"name": "עגבניה", "quantity": 0.5, "unit": "kg"},
        {"name": "בננה", "quantity": 1, "unit": "kg"},
    ],
    "couple": [
        {"name": "לחם", "quantity": 2, "unit": "unit"},
        {"name": "חלב", "quantity": 2, "unit": "unit"},
        {"name": "ביצים", "quantity": 1, "unit": "unit"},
        {"name": "חזה עוף", "quantity": 0.8, "unit": "kg"},
        {"name": "אורז", "quantity": 1, "unit": "unit"},
        {"name": "פסטה", "quantity": 2, "unit": "unit"},
        {"name": "עגבניה", "quantity": 1, "unit": "kg"},
        {"name": "בצל", "quantity": 0.5, "unit": "kg"},
        {"name": "גבינה צהובה", "quantity": 1, "unit": "unit"},
        {"name": "יוגורט", "quantity": 4, "unit": "unit"},
    ],
    "family": [
        {"name": "לחם", "quantity": 2, "unit": "unit"},
        {"name": "חלב", "quantity": 3, "unit": "unit"},
        {"name": "ביצים", "quantity": 2, "unit": "unit"},
        {"name": "חזה עוף", "quantity": 1.2, "unit": "kg"},
        {"name": "בשר טחון", "quantity": 1, "unit": "kg"},
        {"name": "אורז", "quantity": 2, "unit": "unit"},
        {"name": "פסטה", "quantity": 3, "unit": "unit"},
        {"name": "עגבניה", "quantity": 1, "unit": "kg"},
        {"name": "בצל", "quantity": 1, "unit": "kg"},
        {"name": "גבינה צהובה", "quantity": 2, "unit": "unit"},
        {"name": "יוגורט", "quantity": 8, "unit": "unit"},
        {"name": "תפוח", "quantity": 1.5, "unit": "kg"},
        {"name": "בננה", "quantity": 2, "unit": "kg"},
        {"name": "דגני בוקר", "quantity": 2, "unit": "unit"},
    ],
    "healthy": [
        {"name": "חזה עוף", "quantity": 0.6, "unit": "kg"},
        {"name": "סלמון", "quantity": 0.4, "unit": "kg"},
        {"name": "קינואה", "quantity": 1, "unit": "unit"},
        {"name": "תרד", "quantity": 0.3, "unit": "kg"},
        {"name": "ברוקולי", "quantity": 0.5, "unit": "kg"},
        {"name": "עגבניה", "quantity": 0.5, "unit": "kg"},
        {"name": "שמן זית", "quantity": 1, "unit": "unit"},
        {"name": "יוגורט יווני", "quantity": 4, "unit": "unit"},
        {"name": "ביצים", "quantity": 1, "unit": "unit"},
        {"name": "אבוקדו", "quantity": 3, "unit": "unit"},
    ],
    "vegetarian": [
        {"name": "טופו", "quantity": 1, "unit": "unit"},
        {"name": "גרגירי חומוס", "quantity": 1, "unit": "unit"},
        {"name": "עדשים", "quantity": 1, "unit": "unit"},
        {"name": "אורז", "quantity": 1, "unit": "unit"},
        {"name": "פסטה", "quantity": 1, "unit": "unit"},
        {"name": "עגבניה", "quantity": 0.5, "unit": "kg"},
        {"name": "תרד", "quantity": 0.3, "unit": "kg"},
        {"name": "גבינה צהובה", "quantity": 1, "unit": "unit"},
        {"name": "ביצים", "quantity": 1, "unit": "unit"},
        {"name": "יוגורט", "quantity": 4, "unit": "unit"},
    ],
}

PROFILE_OPTIONS = [
    {"id": "basic", "label": "Basic essentials"},
    {"id": "one_person", "label": "Weekly shop for one person"},
    {"id": "couple", "label": "Weekly shop for a couple"},
    {"id": "family", "label": "Weekly family shop"},
    {"id": "healthy", "label": "Healthy groceries"},
    {"id": "vegetarian", "label": "Vegetarian groceries"},
    {"id": "custom", "label": "I’ll provide my own list"},
]


def _split_freeform_list(text: str) -> list[str]:
    return [s.strip() for s in text.replace("\n", ",").split(",") if s.strip()]


async def resolve_weekly_shop_profile(state: AgentState) -> AgentState:
    """A `grocery_list` request with a budget but no items (e.g. "Weekly shopping under
    ₪250") has nothing to build a cart from — asks which kind of weekly shop the user
    means instead of silently building two ₪0.00 carts. `parsed_request["budget"]` is
    untouched here, so it carries through resolve_items/build_*_cart/choose_retailer
    exactly like a budget stated alongside a real item list would."""
    answer = interrupt({
        "reason": "weekly_shop_profile",
        "question": "What kind of weekly shopping do you need?",
        "options": PROFILE_OPTIONS,
    })

    if answer in STARTER_LISTS:
        # Real quantity/unit per item, sized for this profile's household — see
        # STARTER_LISTS above.
        items = [dict(entry) for entry in STARTER_LISTS[answer]]
    else:
        if answer == "custom":
            free_text = interrupt({
                "reason": "weekly_shop_custom_list",
                "question": "Sure — what would you like on your list? (comma-separated is fine)",
                "options": [],
            })
            names = _split_freeform_list(free_text)
        else:
            # The clarification card only ever sends one of the option ids above, but
            # the chat box stays open the whole time — a user who types their list
            # directly instead of clicking "I'll provide my own list" gets the same
            # result rather than an unrecognized-answer error.
            names = _split_freeform_list(answer)
        # A freeform list has no quantity information at all — unchanged from before.
        items = [{"name": n, "quantity": None} for n in names]

    parsed = dict(state["parsed_request"])
    parsed["items"] = items
    return {"parsed_request": parsed}
