from langgraph.types import interrupt

from app.agent.state import AgentState

# Deterministic starter lists, in English (the language-neutral generic term for each
# product) — item names still flow through the exact same resolve_items/build_*_cart path
# as a normal grocery list, so a real retailer catalog that doesn't have an English-named
# match for one of these will surface it as an ordinary missing_items entry, not a crash.
STARTER_LISTS: dict[str, list[str]] = {
    "basic": ["bread", "milk", "eggs", "rice", "pasta", "olive oil", "tomatoes", "onions"],
    "one_person": ["bread", "milk", "eggs", "chicken breast", "rice", "pasta", "tomatoes", "bananas"],
    "couple": [
        "bread", "milk", "eggs", "chicken breast", "rice", "pasta", "tomatoes", "onions",
        "cheese", "yogurt",
    ],
    "family": [
        "bread", "milk", "eggs", "chicken breast", "ground beef", "rice", "pasta", "tomatoes",
        "onions", "cheese", "yogurt", "apples", "bananas", "cereal",
    ],
    "healthy": [
        "chicken breast", "salmon", "quinoa", "spinach", "broccoli", "tomatoes", "olive oil",
        "greek yogurt", "eggs", "avocado",
    ],
    "vegetarian": [
        "tofu", "chickpeas", "lentils", "rice", "pasta", "tomatoes", "spinach", "cheese",
        "eggs", "yogurt",
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
