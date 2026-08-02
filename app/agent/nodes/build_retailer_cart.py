from app.agent.state import AgentState


async def _suggest_trade_off(client, retailer: str, most_expensive: dict) -> dict | None:
    candidates = await client.search_product(most_expensive["name"], retailer)
    cheaper = [
        c for c in candidates
        if c["item_code"] != most_expensive["item_code"] and c["price"] < most_expensive["subtotal"]
    ]
    if not cheaper:
        return None
    alt = min(cheaper, key=lambda c: c["price"])
    return {
        "item_name": most_expensive["name"],
        "current_choice": most_expensive["product_name"],
        "suggested_choice": alt["name"],
        "savings": round(most_expensive["subtotal"] - alt["price"], 2),
    }


def make_build_retailer_cart(retailer: str, client):
    async def build_cart(state: AgentState) -> AgentState:
        parsed = state["parsed_request"]
        lines: list[dict] = []
        missing: list[dict] = []

        for item in parsed["items"]:
            name = item["name"]
            label = state["resolved_choices"].get(name, name)
            candidates = await client.search_product(label, retailer)
            if not candidates:
                missing.append({"name": name, "reason": "not_found"})
                continue

            best = min(candidates, key=lambda c: c["price"])
            price_info = await client.get_product_price(retailer, best["item_code"])
            lines.append({
                "name": name,
                "item_code": best["item_code"],
                "product_name": best["name"],
                "unit_price": price_info["unit_price"],
                "qty": 1,
                "subtotal": price_info["price"],
            })

        total = sum(line["subtotal"] for line in lines)
        budget = parsed.get("budget")
        over_budget_by = round(total - budget, 2) if budget is not None and total > budget else None

        trade_offs = []
        if over_budget_by is not None and lines:
            most_expensive = max(lines, key=lambda l: l["subtotal"])
            suggestion = await _suggest_trade_off(client, retailer, most_expensive)
            if suggestion:
                trade_offs.append(suggestion)

        cart = {
            "retailer": retailer,
            "items": lines,
            "missing_items": missing,
            "total": total,
            "budget": budget,
            "over_budget_by": over_budget_by,
            "trade_off_suggestions": trade_offs,
        }
        return {"retailer_carts": {**state.get("retailer_carts", {}), retailer: cart}}

    return build_cart
