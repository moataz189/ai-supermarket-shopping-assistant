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
STARTER_LISTS: dict[str, list[str]] = {
    "basic": ["לחם", "חלב", "ביצים", "אורז", "פסטה", "שמן זית", "עגבניה", "בצל"],
    "one_person": ["לחם", "חלב", "ביצים", "חזה עוף", "אורז", "פסטה", "עגבניה", "בננה"],
    "couple": [
        "לחם", "חלב", "ביצים", "חזה עוף", "אורז", "פסטה", "עגבניה", "בצל",
        "גבינה צהובה", "יוגורט",
    ],
    "family": [
        "לחם", "חלב", "ביצים", "חזה עוף", "בשר טחון", "אורז", "פסטה", "עגבניה",
        "בצל", "גבינה צהובה", "יוגורט", "תפוח", "בננה", "דגני בוקר",
    ],
    "healthy": [
        "חזה עוף", "סלמון", "קינואה", "תרד", "ברוקולי", "עגבניה", "שמן זית",
        "יוגורט יווני", "ביצים", "אבוקדו",
    ],
    "vegetarian": [
        "טופו", "גרגירי חומוס", "עדשים", "אורז", "פסטה", "עגבניה", "תרד", "גבינה צהובה",
        "ביצים", "יוגורט",
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
        names = STARTER_LISTS[answer]
    elif answer == "custom":
        free_text = interrupt({
            "reason": "weekly_shop_custom_list",
            "question": "Sure — what would you like on your list? (comma-separated is fine)",
            "options": [],
        })
        names = _split_freeform_list(free_text)
    else:
        # The clarification card only ever sends one of the option ids above, but the
        # chat box stays open the whole time — a user who types their list directly
        # instead of clicking "I'll provide my own list" gets the same result rather
        # than an unrecognized-answer error.
        names = _split_freeform_list(answer)

    parsed = dict(state["parsed_request"])
    parsed["items"] = [{"name": n, "quantity": None} for n in names]
    return {"parsed_request": parsed}
