from app.agent.state import AgentState


def recipe_not_found(state: AgentState) -> AgentState:
    """Terminal node for a recipe search that returned zero candidates — nothing to shop
    for, so this short-circuits straight to a finalize-shaped result instead of running
    the empty-cart pipeline (resolve_items/build_*_cart/choose_retailer) for no reason."""
    query = state["parsed_request"].get("recipe_query")
    return {
        "status": "partial_success",
        "warnings": [{"code": "recipe_not_found", "query": query}],
        "clarification": None,
        "final_result": {
            "carts": {},
            "chosen_retailer": None,
            "retailer_cart_result": None,
        },
    }
