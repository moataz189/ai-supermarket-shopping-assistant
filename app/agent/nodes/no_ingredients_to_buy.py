from app.agent.recipe_info import recipe_info
from app.agent.state import AgentState


def no_ingredients_to_buy(state: AgentState) -> AgentState:
    """Terminal node for when the user unchecked every ingredient on the selection
    screen — nothing to shop for, so this short-circuits straight to a finalize-shaped
    result instead of running the empty-cart pipeline (resolve_items/build_*_cart/
    choose_retailer/prepare_retailer_cart) for no reason (spec: never build ₪0 carts,
    never call the Supermarket or Retailer-Cart MCPs for this case).

    The recipe info shown here is the *full* original ingredient list
    (`state["recipe_items"]`, untouched by the selection filter that emptied
    `parsed_request["items"]`) — the user still gets to see what the recipe actually
    called for, just told they already have everything, not just an empty list."""
    parsed = state["parsed_request"]
    recipe_items = state.get("recipe_items", [])
    recipe = recipe_info({**state, "parsed_request": {**parsed, "items": recipe_items}})

    return {
        "status": "success",
        "warnings": [],
        "clarification": None,
        "retailer_carts": {},
        "final_result": {
            "carts": {},
            "chosen_retailer": None,
            "retailer_cart_result": None,
            "message": "You already have all the ingredients for this recipe.",
            "recipe": recipe,
        },
    }
