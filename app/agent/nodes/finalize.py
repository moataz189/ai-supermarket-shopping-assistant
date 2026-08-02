def finalize(state):
    carts = state["retailer_carts"]
    warnings = []
    for retailer, cart in carts.items():
        if cart["missing_items"]:
            warnings.append({"code": "product_not_found", "retailer": retailer, "items": cart["missing_items"]})
        if cart["over_budget_by"] is not None:
            warnings.append({"code": "budget_exceeded", "retailer": retailer, "over_budget_by": cart["over_budget_by"]})

    return {
        "status": "partial_success" if warnings else "success",
        "warnings": warnings,
        "clarification": None,
        "final_result": {"carts": carts, "chosen_retailer": state.get("chosen_retailer")},
    }
