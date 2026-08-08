from app.agent.state import AgentState
from app.dietary.rules import find_substitute_query, forbidden_tags, tags_for_name


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
        forbidden = forbidden_tags(parsed.get("dietary_constraints", []))
        dietary_conflicts = state.get("dietary_conflicts", [])
        lines: list[dict] = []
        missing: list[dict] = []

        for item in parsed["items"]:
            name = item["name"]
            # Prefer THIS retailer's own resolved catalog product name (resolved_choices
            # is now per-retailer, CP9 follow-up 2026-08-08 — resolving one retailer's
            # ambiguity must never borrow another retailer's chosen label, since the two
            # retailers' real product names for "the same" item are frequently different
            # strings); otherwise fall back to search_name — always tried in Hebrew when
            # a translation exists, regardless of this conversation's own language, since
            # the real catalog is Hebrew-only — so this independent re-search still has
            # a real chance of matching. See resolve_items.py's own comment.
            label = (
                state["resolved_choices"].get(name, {}).get(retailer)
                or item.get("search_name")
                or item.get("display_name")
                or name
            )
            candidates = await client.search_product(label, retailer)
            if forbidden:
                compliant = [c for c in candidates if not (tags_for_name(c["name"]) & forbidden)]
                if not compliant:
                    sub_query = find_substitute_query(name, forbidden)
                    compliant = await client.search_product(sub_query, retailer) if sub_query else []
                candidates = compliant
            if not candidates:
                reason = "dietary_conflict" if name in dietary_conflicts else "not_found"
                missing.append({"name": item.get("display_name") or name, "reason": reason})
                continue

            best = min(candidates, key=lambda c: c["price"])
            price_info = await client.get_product_price(retailer, best["item_code"])
            # `quantity`/`unit` are only ever set on recipe-derived items (CP7's
            # get_recipe_ingredients) — None for ordinary grocery-list/weekly-shop items,
            # exactly the pre-existing behavior. `qty` here (used only for this
            # retailer's own price-comparison subtotal/total/budget math) intentionally
            # stays 1 regardless — recipe quantities are a real amount to add to the
            # retailer's cart, not a multiplier on the comparison-view price, and scaling
            # that math is out of scope for this fix (see docs/plan). The retailer cart's
            # actual add-to-cart quantity is requested_quantity/requested_unit below,
            # threaded through prepare_retailer_cart.py to the Retailer-Cart MCP, where
            # each retailer's own selling-method/increment rules decide the real
            # cart_quantity/cart_unit — see mcp_servers/retailer_cart_mcp/quantity.py.
            lines.append({
                "name": name,
                "item_code": best["item_code"],
                "product_name": best["name"],
                "unit_price": price_info["unit_price"],
                "qty": 1,
                "requested_quantity": item.get("quantity"),
                "requested_unit": item.get("unit") if item.get("quantity") is not None else None,
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
