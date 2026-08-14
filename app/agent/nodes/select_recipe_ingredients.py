from langgraph.types import interrupt

from app.agent.recipe_info import recipe_info
from app.agent.state import AgentState


def _build_ingredient_options(items: list[dict]) -> list[dict]:
    """Builds the interrupt payload's `ingredients` list. Every ingredient is pre-selected
    (`selected: True`) — explicit product decision: the user may already have some of
    what a recipe calls for, but *not* having anything at home is the common case, so
    they should be able to just press Continue rather than having to opt every ingredient
    back in one at a time."""
    return [
        {
            "id": item["name"],
            "name": item["name"],
            "display_name": item.get("display_name") or item["name"],
            "quantity": item.get("quantity"),
            "unit": item.get("unit"),
            "selected": True,
        }
        for item in items
    ]


def _filter_selected(items: list[dict], selected_ids) -> list[dict]:
    """Filters `items` down to only those whose name is in `selected_ids`, preserving
    each item's original dict as-is (quantity/unit survive untouched). Validated against
    the real item names first — an unknown/stale id in the resume answer (e.g. left over
    from a previous turn's ingredient list) is silently ignored rather than trusted
    blindly or crashing the flow. `selected_ids` being falsy (None, or the user cleared
    every checkbox) simply means nothing is selected — same treatment either way."""
    valid_ids = {item["name"] for item in items}
    selected = set(selected_ids or []) & valid_ids
    return [item for item in items if item["name"] in selected]


async def select_recipe_ingredients(state: AgentState) -> AgentState:
    """Pauses the recipe flow after get_recipe_ingredients.py has fetched/scaled the full
    ingredient list, and before resolve_items ever runs — the user may already have some
    ingredients at home and shouldn't be forced to search for or buy them (spec: CP10).

    The full list is preserved in `recipe_items` regardless of what gets selected;
    `parsed_request["items"]` — the one field every downstream node (resolve_items,
    build_retailer_cart, choose_retailer) already consumes — becomes just the selected
    subset, so nothing downstream needs any awareness that ingredient selection exists at
    all. An unselected ingredient therefore never reaches resolve_items, never gets
    searched, never appears as missing, and never affects a retailer's total — it simply
    isn't in the list they see.
    """
    parsed = state["parsed_request"]
    recipe_items = parsed["items"]

    payload = {
        "reason": "recipe_ingredient_selection",
        "question": "Which ingredients do you need to buy?",
        "ingredients": _build_ingredient_options(recipe_items),
        # Reuses the existing recipe/title/servings shape (already sent on the
        # retailer_choice interrupt) so the selection screen can show the same header
        # without a second, redundant recipe-summary field.
        "recipe": recipe_info(state),
    }
    answer = interrupt(payload)
    while not isinstance(answer, list):
        # Same class of bug as resolve_ambiguity.py (2026-08-14): the chat box's free-text
        # input stays open while this card is showing. A typed string isn't a crash here
        # (`set(str) & valid_ids` just silently selects nothing, since valid_ids are full
        # ingredient names, not single characters) but it's still the wrong answer to the
        # wrong question -- re-asks instead of silently discarding every ingredient.
        answer = interrupt(payload)

    selected_items = _filter_selected(recipe_items, answer)

    return {
        "recipe_items": recipe_items,
        "selected_recipe_items": [item["name"] for item in selected_items],
        "parsed_request": {**parsed, "items": selected_items},
    }


def route_after_ingredient_selection(state: AgentState) -> str:
    return "resolve_items" if state["parsed_request"]["items"] else "no_ingredients_to_buy"
