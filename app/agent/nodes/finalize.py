from app.agent.recipe_info import recipe_info


def finalize(state):
    carts = state["retailer_carts"]
    chosen_retailer = state.get("chosen_retailer")
    # Once the user has committed to a specific retailer, the other retailer's warnings
    # (missing items, budget overage) are no longer relevant to what they're about to do —
    # only surface warnings for the retailer actually chosen. Declining ("just show me
    # this") leaves chosen_retailer unset, so both retailers' warnings still apply.
    relevant_carts = {chosen_retailer: carts[chosen_retailer]} if chosen_retailer else carts
    warnings = []
    for retailer, cart in relevant_carts.items():
        if cart["missing_items"]:
            warnings.append({"code": "product_not_found", "retailer": retailer, "items": cart["missing_items"]})
        if cart["over_budget_by"] is not None:
            warnings.append({"code": "budget_exceeded", "retailer": retailer, "over_budget_by": cart["over_budget_by"]})

    return {
        "status": "partial_success" if warnings else "success",
        "warnings": warnings,
        "clarification": None,
        "final_result": {
            "carts": carts,
            "chosen_retailer": state.get("chosen_retailer"),
            "retailer_cart_result": state.get("retailer_cart_result"),
            "recipe": recipe_info(state),
        },
    }
