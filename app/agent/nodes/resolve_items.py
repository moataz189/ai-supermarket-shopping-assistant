from app.agent.state import AgentState
from app.dietary.rules import find_substitute_query, forbidden_tags, tags_for_name

RETAILERS = ["shufersal", "rami_levy"]


async def _candidates_by_retailer(
    client, name: str, forbidden: set[str]
) -> dict[str, list[dict]]:
    """Keeps each retailer's candidates separate — never merged away — so the user can
    see which retailer actually carries which option before choosing (spec §3). Candidates
    that violate `forbidden` dietary tags are filtered out here too, so a filtered-out option
    never appears in the per-retailer breakdown shown to the user (CP7)."""
    result = {}
    for retailer in RETAILERS:
        candidates = await client.search_product(name, retailer)
        if forbidden:
            candidates = [c for c in candidates if not (tags_for_name(c["name"]) & forbidden)]
        result[retailer] = candidates
    return result


def _unique_labels(candidates_by_retailer: dict[str, list[dict]]) -> list[dict]:
    """Dedups by name *across* retailers into the set of distinct 'kinds' the user might
    mean — used only to decide/present what to resolve, never to build a cart directly."""
    merged: dict[str, dict] = {}
    for candidates in candidates_by_retailer.values():
        for c in candidates:
            merged.setdefault(c["name"].strip().lower(), c)
    return list(merged.values())[:5]


async def _resolve_item(
    search_name: str, candidates: list[dict], brand_preference: str | None, selection_preference: str,
) -> tuple[str | None, bool]:
    """`search_name` is the (possibly localized) query actually used to find `candidates`
    — see `resolve_items`'s own `search_name` for why this isn't always the item's
    canonical name. `candidates` is the deduped, cross-retailer set from
    `_unique_labels`. Returns (resolved_label_or_None, still_ambiguous). A resolved label
    is a product name used as the search query in each retailer's own catalog later — not
    an item_code."""
    if not candidates:
        return search_name, False  # nothing matched anywhere; let per-retailer building report it missing
    if len(candidates) == 1:
        return candidates[0]["name"], False

    exact = [c for c in candidates if c["name"].strip().lower() == search_name.strip().lower()]
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
        dietary_conflicts = list(state.get("dietary_conflicts", []))
        ambiguous_item = None
        forbidden = forbidden_tags(parsed.get("dietary_constraints", []))

        for item in parsed["items"]:
            name = item["name"]
            if name in resolved_choices or name in dietary_conflicts:
                continue
            # Recipe-derived items carry an English canonical `name` (Spoonacular) and a
            # `search_name` that's *always* tried in Hebrew when a translation exists
            # (see get_recipe_ingredients.py) — the real catalog is Hebrew-only
            # regardless of what language this conversation is in, so searching with the
            # English name never matches even when the equivalent product genuinely
            # exists (confirmed live, twice: once for a Hebrew-language conversation,
            # then again for an English one — `display_name` alone isn't enough, since it
            # follows the conversation's own language and stays English there).
            # Grocery-list items have no search_name/display_name at all (already typed
            # in the user's own language), so this is a no-op fallback for them.
            search_name = item.get("search_name") or item.get("display_name") or name
            if name not in item_candidates:
                item_candidates[name] = await _candidates_by_retailer(client, search_name, forbidden)
            by_retailer = item_candidates[name]
            unique = _unique_labels(by_retailer)

            if not unique and forbidden:
                sub_query = find_substitute_query(name, forbidden)
                if sub_query is None:
                    dietary_conflicts.append(name)
                    continue
                by_retailer = await _candidates_by_retailer(client, sub_query, forbidden)
                item_candidates[name] = by_retailer
                unique = _unique_labels(by_retailer)

            label, still_ambiguous = await _resolve_item(
                search_name, unique,
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
            "dietary_conflicts": dietary_conflicts,
        }

    return resolve_items
