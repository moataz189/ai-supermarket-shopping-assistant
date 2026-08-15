from app.agent.nodes.product_relevance import filter_relevant_candidates
from app.agent.quantity import estimate_weight_kg_for_count, estimated_package_count, is_count_unit
from app.agent.state import AgentState
from app.dietary.rules import find_substitute_query, forbidden_tags, tags_for_name

_WEIGHT_PACKAGE_UNITS = {"g", "gram", "grams", "kg", "kilogram", "kilograms"}


def _estimated_weight_subtotal(price_info: dict, quantity, unit) -> float | None:
    """Best-effort price for a bare count against a product sold by weight (e.g. "1
    onion" against loose onions priced per kg) -- see app/agent/quantity.py's
    estimate_weight_kg_for_count for why this is the same 0.5 kg/unit estimate the real
    cart-add uses. Returns None when the mismatch isn't this specific case (count vs.
    weight-only package), so the caller falls back to its existing behavior unchanged."""
    package_unit = price_info.get("package_unit")
    if unit is None or not is_count_unit(unit) or package_unit is None:
        return None
    if package_unit.strip().lower() not in _WEIGHT_PACKAGE_UNITS:
        return None
    grams = estimate_weight_kg_for_count(quantity, unit) * 1000
    return round(price_info["unit_price"] * grams, 2)


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


def _label_for(name: str, item: dict, resolved_choices: dict, retailer: str) -> str:
    # Prefer THIS retailer's own resolved catalog product name (resolved_choices is
    # per-retailer, CP9 follow-up, 2026-08-08 — a retailer's real product name for "the
    # same" item can genuinely differ from another retailer's); otherwise fall back to
    # search_name — always tried in Hebrew when a translation exists, regardless of this
    # conversation's own language, since the real catalog is Hebrew-only.
    return (
        resolved_choices.get(name, {}).get(retailer)
        or item.get("search_name")
        or item.get("display_name")
        or name
    )


async def _candidates_for(
    client, llm, retailer: str, name: str, label: str, item: dict,
    forbidden: set[str], dietary_conflicts: list[str],
) -> tuple[list[dict], dict | None]:
    """Returns (candidates, missing_entry). `missing_entry` is None when candidates were
    found; otherwise it's the dict to append to this retailer's `missing_items`.

    This is a fresh, independent catalog search by `label` (the already-resolved product
    name/search term) — real user report (2026-08-14): resolve_items.py's own relevance
    filter can correctly narrow *its* candidates, but this search re-queries the catalog
    from scratch and previously fed the result straight to `min(price)` with no semantic
    check at all, so a cheap unrelated product containing `label` as a substring (a
    prepared "mashed potato with onion" dish for a plain "onion" search) could still win
    on price alone. Relevance-filtered here too, the same way, whenever there's more than
    one candidate to choose between — the whole point of this second search existing at
    all is to price the *cheapest genuinely matching* product, not just the cheapest
    catalog hit."""
    candidates = await client.search_product(label, retailer)
    if forbidden:
        compliant = [c for c in candidates if not (tags_for_name(c["name"]) & forbidden)]
        if not compliant:
            sub_query = find_substitute_query(name, forbidden)
            compliant = await client.search_product(sub_query, retailer) if sub_query else []
        candidates = compliant

    if len(candidates) > 1:
        # A candidate matching `label` verbatim is unambiguous -- resolve_items.py's own
        # _resolve_item already has this exact-match shortcut for its first search; this
        # second, independent search had no equivalent protection, so it stayed exposed
        # to relevance-filter LLM non-determinism even when a deterministic exact match
        # was sitting right there (real user report, 2026-08-16: a "tomato sauce"
        # candidate kept winning here over an exact-match plain "tomato" product).
        exact = [c for c in candidates if c["name"].strip().lower() == label.strip().lower()]
        if len(exact) == 1:
            candidates = exact
        else:
            relevance_name = item.get("search_name") or item.get("display_name") or name
            candidates = await filter_relevant_candidates(llm, relevance_name, candidates)

    if not candidates:
        reason = "dietary_conflict" if name in dietary_conflicts else "not_found"
        return [], {"name": name, "reason": reason}
    return candidates, None


def _estimated_cost(price_info: dict, quantity: float | None, unit: str | None) -> float:
    """Best-effort cost for one cart line honoring the item's real required quantity —
    used only by the open-ended/weekly-profile budget-constrained selection below to
    decide whether a candidate fits the remaining budget. `unit_price` is price per
    gram/ml/package-unit (see app/db/repositories.py's unit_price); "kg" is the only
    weight unit STARTER_LISTS/recipes ever attach to a grocery-list item, so a "kg"
    request is priced via unit_price (price-per-gram) x grams requested. Any other unit
    (or no quantity at all) is priced as a straight package-count multiple of the
    package price, matching how a plain unit count (loaves, cartons...) is actually
    sold."""
    if quantity is None or unit is None:
        return price_info["price"]
    if unit == "kg":
        return round(price_info["unit_price"] * quantity * 1000, 2)
    return round(price_info["price"] * quantity, 2)


async def _add_every_item(
    client, llm, retailer: str, items: list[dict], resolved_choices: dict, forbidden: set[str],
    dietary_conflicts: list[str],
) -> tuple[list[dict], list[dict]]:
    """The pre-existing behavior for explicit shopping lists and recipes: every item is
    resolved and added regardless of budget — the user's explicit intent is never
    silently dropped (budget-constrained selection is reserved for
    open_ended_budget_selection carts, see _select_items_within_budget below)."""
    lines: list[dict] = []
    missing: list[dict] = []
    for item in items:
        name = item["name"]
        label = _label_for(name, item, resolved_choices, retailer)
        candidates, missing_entry = await _candidates_for(
            client, llm, retailer, name, label, item, forbidden, dietary_conflicts
        )
        if missing_entry is not None:
            missing.append({
                "name": item.get("display_name") or missing_entry["name"],
                "reason": missing_entry["reason"],
            })
            continue

        best = min(candidates, key=lambda c: c["price"])
        price_info = await client.get_product_price(retailer, best["item_code"])
        # `quantity`/`unit` are only ever set on recipe-derived items (CP7's
        # get_recipe_ingredients) — None for ordinary grocery-list items. `qty` here
        # (a plain product count, distinct from `estimated_package_count` below) stays 1
        # regardless — the retailer cart's actual add-to-cart quantity is
        # requested_quantity/requested_unit below, threaded through
        # prepare_retailer_cart.py.
        quantity, unit = item.get("quantity"), item.get("unit")
        package_size, package_unit = price_info.get("package_size"), price_info.get("package_unit")
        # Best-effort estimate of how many whole packages this recipe amount will
        # actually need (real user report: "1000 g pasta" matched to a 500 g package
        # showed a single package's price/quantity in the comparison view, even though
        # 2 packages is what the Retailer-Cart MCP would go on to actually buy) — None
        # (and the comparison view falls back to the raw amount, unchanged) whenever
        # there's no quantity/package size to compare, or they're not the same kind of
        # quantity (see app/agent/quantity.py).
        count = None
        if quantity is not None and unit is not None and package_size is not None and package_unit is not None:
            count = estimated_package_count(quantity, unit, package_size, package_unit)
        if count is not None:
            subtotal = round(price_info["price"] * count, 2)
        else:
            subtotal = _estimated_weight_subtotal(price_info, quantity, unit) or price_info["price"]

        lines.append({
            "name": name,
            "item_code": best["item_code"],
            "product_name": best["name"],
            "unit_price": price_info["unit_price"],
            "qty": 1,
            "requested_quantity": quantity,
            "requested_unit": unit if quantity is not None else None,
            "subtotal": subtotal,
            "package_size": package_size,
            "package_unit": package_unit,
            "estimated_package_count": count,
        })
    return lines, missing


async def _select_items_within_budget(
    client, llm, retailer: str, items: list[dict], resolved_choices: dict, forbidden: set[str],
    dietary_conflicts: list[str], budget: float,
) -> tuple[list[dict], list[dict], float]:
    """Only used for open_ended_budget_selection carts (a budget-only request with no
    items, or its "custom" freeform follow-up — see resolve_weekly_shop_profile.py).
    Walks `items` in their existing stable order (STARTER_LISTS is already curated
    "useful/common items first" with reasonable category spread) and greedily adds each
    item's cheapest matching candidate, using its real required quantity
    (_estimated_cost) — skipping (never adding) any single item whose cost would push
    the running total past `budget * 1.10`, then continuing to try the rest of the list
    rather than stopping outright, so a handful of expensive items don't starve an
    otherwise-affordable cart. Deterministic: no randomness, stable input order, stable
    price-based tie-break per item (cheapest candidate wins, same as the non-budget
    path)."""
    allowed_max = round(budget * 1.10, 2)
    lines: list[dict] = []
    missing: list[dict] = []
    running_total = 0.0

    for item in items:
        name = item["name"]
        label = _label_for(name, item, resolved_choices, retailer)
        candidates, missing_entry = await _candidates_for(
            client, llm, retailer, name, label, item, forbidden, dietary_conflicts
        )
        if missing_entry is not None:
            missing.append({
                "name": item.get("display_name") or missing_entry["name"],
                "reason": missing_entry["reason"],
            })
            continue

        best = min(candidates, key=lambda c: c["price"])
        price_info = await client.get_product_price(retailer, best["item_code"])
        cost = _estimated_cost(price_info, item.get("quantity"), item.get("unit"))

        if round(running_total + cost, 2) > allowed_max:
            continue  # doesn't fit within the tolerance -- skip it, keep trying the rest

        running_total = round(running_total + cost, 2)
        lines.append({
            "name": name,
            "item_code": best["item_code"],
            "product_name": best["name"],
            "unit_price": price_info["unit_price"],
            "qty": 1,
            "requested_quantity": item.get("quantity"),
            "requested_unit": item.get("unit") if item.get("quantity") is not None else None,
            "subtotal": cost,
            "package_size": price_info.get("package_size"),
            "package_unit": price_info.get("package_unit"),
            # Not computed for the open-ended/budget-selection path -- _estimated_cost
            # above already prices this line by the real requested quantity for budget
            # purposes, so there's no separate "packages needed" estimate to show here.
            "estimated_package_count": None,
        })

    return lines, missing, running_total


def make_build_retailer_cart(retailer: str, client, llm):
    async def build_cart(state: AgentState) -> AgentState:
        parsed = state["parsed_request"]
        forbidden = forbidden_tags(parsed.get("dietary_constraints", []))
        dietary_conflicts = state.get("dietary_conflicts", [])
        resolved_choices = state["resolved_choices"]
        budget = parsed.get("budget")
        open_ended = state.get("open_ended_budget_selection", False)

        trade_offs: list[dict] = []
        no_items_fit_budget = False

        if open_ended and budget is not None:
            lines, missing, total = await _select_items_within_budget(
                client, llm, retailer, parsed["items"], resolved_choices, forbidden, dietary_conflicts, budget,
            )
            no_items_fit_budget = not lines
        else:
            lines, missing = await _add_every_item(
                client, llm, retailer, parsed["items"], resolved_choices, forbidden, dietary_conflicts,
            )
            total = sum(line["subtotal"] for line in lines)

        over_budget_by = round(total - budget, 2) if budget is not None and total > budget else None
        allowed_max = round(budget * 1.10, 2) if budget is not None else None

        if not open_ended and over_budget_by is not None and lines:
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
            "allowed_max": allowed_max,
            "over_budget_by": over_budget_by,
            "no_items_fit_budget": no_items_fit_budget,
            "trade_off_suggestions": trade_offs,
        }
        return {"retailer_carts": {**state.get("retailer_carts", {}), retailer: cart}}

    return build_cart
