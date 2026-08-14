from langgraph.types import interrupt

from app.agent.nodes.resolve_items import _dedupe_by_name


async def resolve_ambiguity(state):
    """Asks the user to disambiguate a product — independently per retailer (CP9
    follow-up, 2026-08-08). Previously this merged both retailers' candidates into one
    flat list and asked for a single choice used for both — which only worked when both
    retailers happened to name "the same" grocery item with byte-identical text; a real
    catalog routinely doesn't (different phrasing, spelling, private-label branding), so
    picking one retailer's exact name left the other retailer unable to find its own,
    differently-named product at all. Only a retailer that's genuinely ambiguous on its
    own candidates (resolve_items.py already auto-resolved anything with exactly one
    candidate, without asking) appears here at all — a retailer that already resolved,
    or found nothing, is left untouched by this node."""
    item_name = state["pending_clarification_item"]
    by_retailer = state["item_candidates"][item_name]
    already_resolved = state.get("resolved_choices", {}).get(item_name, {})

    options_by_retailer = {}
    for retailer, candidates in by_retailer.items():
        if retailer in already_resolved:
            continue
        deduped = _dedupe_by_name(candidates)
        if len(deduped) < 2:
            continue  # auto-resolved (or empty) already — nothing to ask for this retailer
        options_by_retailer[retailer] = [
            {"id": c["name"], "label": c["name"], "price": c["price"]} for c in deduped
        ]

    # `answer` is one choice per retailer actually offered above — e.g.
    # {"shufersal": "Tara", "rami_levy": "President"} — never a single flat string;
    # a retailer this node didn't ask about is simply absent from `answer` and stays
    # whatever resolve_items.py already resolved it to (or left unresolved).
    payload = {
        "reason": "ambiguous_product",
        "question": f"I found a few options for '{item_name}' — which one did you mean?",
        "options_by_retailer": options_by_retailer,
    }
    answer = interrupt(payload)
    while not isinstance(answer, dict):
        # Real production crash (2026-08-14): the chat box's free-text input stays open
        # the whole time a clarification is pending (by design -- some clarifications,
        # like resolve_weekly_shop_profile's, genuinely accept typed text). Typing
        # something here instead of clicking an option sends a bare string, which doesn't
        # fit this clarification's per-retailer shape -- re-asks the same question rather
        # than crashing on `**answer`.
        answer = interrupt(payload)
    resolved = dict(state.get("resolved_choices", {}))
    resolved[item_name] = {**resolved.get(item_name, {}), **answer}
    return {"resolved_choices": resolved, "pending_clarification_item": None}


def route_after_resolve(state) -> str:
    return "resolve_ambiguity" if state.get("pending_clarification_item") else "build_shufersal_cart"
