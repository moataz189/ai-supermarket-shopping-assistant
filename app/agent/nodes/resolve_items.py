from app.agent.state import AgentState

RETAILERS = ["shufersal", "rami_levy"]


async def _candidates_by_retailer(client, name: str) -> dict[str, list[dict]]:
    """Keeps each retailer's candidates separate — never merged away — so the user can
    see which retailer actually carries which option before choosing (spec §3)."""
    return {retailer: await client.search_product(name, retailer) for retailer in RETAILERS}


def _unique_labels(candidates_by_retailer: dict[str, list[dict]]) -> list[dict]:
    """Dedups by name *across* retailers into the set of distinct 'kinds' the user might
    mean — used only to decide/present what to resolve, never to build a cart directly."""
    merged: dict[str, dict] = {}
    for candidates in candidates_by_retailer.values():
        for c in candidates:
            merged.setdefault(c["name"].strip().lower(), c)
    return list(merged.values())[:5]


async def _resolve_item(
    name: str, candidates: list[dict], brand_preference: str | None, selection_preference: str,
) -> tuple[str | None, bool]:
    """`candidates` is the deduped, cross-retailer set from `_unique_labels`. Returns
    (resolved_label_or_None, still_ambiguous). A resolved label is a product name used as
    the search query in each retailer's own catalog later — not an item_code."""
    if not candidates:
        return name, False  # nothing matched anywhere; let per-retailer building report it missing
    if len(candidates) == 1:
        return candidates[0]["name"], False

    exact = [c for c in candidates if c["name"].strip().lower() == name.strip().lower()]
    if len(exact) == 1:
        return exact[0]["name"], False

    if brand_preference:
        matches = [c for c in candidates if brand_preference.strip().lower() in c["name"].strip().lower()]
        if len(matches) == 1:
            return matches[0]["name"], False

    if selection_preference == "cheapest":
        return min(candidates, key=lambda c: c["price"])["name"], False

    return None, True


def make_resolve_items(client):
    async def resolve_items(state: AgentState) -> AgentState:
        parsed = state["parsed_request"]
        item_candidates = dict(state.get("item_candidates", {}))
        resolved_choices = dict(state.get("resolved_choices", {}))
        ambiguous_item = None

        for item in parsed["items"]:
            name = item["name"]
            if name in resolved_choices:
                continue
            if name not in item_candidates:
                item_candidates[name] = await _candidates_by_retailer(client, name)
            by_retailer = item_candidates[name]

            label, still_ambiguous = await _resolve_item(
                name, _unique_labels(by_retailer),
                parsed.get("brand_preference"), parsed.get("selection_preference", "no_preference"),
            )
            if label is not None:
                resolved_choices[name] = label
            elif still_ambiguous and ambiguous_item is None:
                ambiguous_item = name

        return {
            "item_candidates": item_candidates,
            "resolved_choices": resolved_choices,
            "pending_clarification_item": ambiguous_item,
        }

    return resolve_items
