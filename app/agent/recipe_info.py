def recipe_info(state) -> dict | None:
    """The scaled recipe ingredient list (name/quantity/unit), shown to the user before
    or alongside the retailer comparison so they can see what a recipe actually requires
    without having to infer it from the final cart. Only meaningful for an actual recipe
    request — a plain grocery-list/weekly-shop request has no chosen_recipe at all, and
    parsed_request["items"] there never carries a real quantity/unit (see
    build_retailer_cart.py), so there'd be nothing useful to show here anyway.

    Shared by choose_retailer.py (surfaced on the retailer_choice interrupt, before a
    retailer is picked) and finalize.py (surfaced on every subsequent turn) — both nodes
    see this same shape of state at the point they call it.
    """
    parsed = state.get("parsed_request")
    if not parsed or parsed.get("request_type") != "recipe":
        return None
    chosen_recipe = state.get("chosen_recipe") or {}
    return {
        "title": chosen_recipe.get("display_title") or chosen_recipe.get("title"),
        "servings": chosen_recipe.get("servings"),
        "ingredients": [
            {
                "name": item.get("display_name") or item["name"],
                "quantity": item.get("quantity"),
                "unit": item.get("unit"),
            }
            for item in parsed.get("items", [])
        ],
    }
