from app.agent.nodes.product_relevance import filter_relevant_candidates
from app.agent.state import AgentState
from app.dietary.rules import find_substitute_query, forbidden_tags, tags_for_name

RETAILERS = ["shufersal", "rami_levy"]

# A DISPLAY limit only (2026-08-14 fix) -- how many relevant candidates to show the user
# in the ambiguity UI when there's a real choice to make. Must never gate what reaches
# semantic relevance filtering or the ambiguity decision itself (still_ambiguous is
# always based on the *full* relevant set) -- conflating the two caused genuinely
# relevant products (real milk, enough pasta options, multiple real rice/tuna products)
# to be silently lost before the relevance filter ever saw them.
MAX_CANDIDATES_SHOWN = 5


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


def _dedupe_by_name(candidates: list[dict]) -> list[dict]:
    """Dedups a single retailer's own candidates by exact name — a retailer's real
    catalog can have two rows sharing an exact name (different item_codes); presenting
    duplicate-labeled options to choose from would be confusing and pointless. Scoped to
    one retailer only (CP9 follow-up, 2026-08-08) — candidates are never merged *across*
    retailers anymore, since two retailers' own product names for "the same" grocery item
    are frequently different strings in a real catalog (different phrasing, spelling,
    private-label branding) and forcing a single shared label across both broke matching
    for whichever retailer's catalog didn't actually contain that exact text.

    Deliberately does NOT cap the result (2026-08-14 fix — see MAX_CANDIDATES_SHOWN's own
    docstring): a real user report showed genuinely relevant products (real milk, enough
    pasta options, multiple real rice/tuna products) getting lost because a display-sized
    cap was applied here, *before* semantic relevance filtering ever ran on the broader
    raw pool. Deduping only, no truncation — the internal candidate pool relevance
    filtering judges must stay as broad as retrieval actually returned."""
    merged: dict[str, dict] = {}
    for c in candidates:
        merged.setdefault(c["name"].strip().lower(), c)
    return list(merged.values())


async def _resolve_item(
    llm, search_name: str, candidates: list[dict], brand_preference: str | None, selection_preference: str,
) -> tuple[str | None, bool, list[dict]]:
    """`search_name` is the (possibly localized) query actually used to find `candidates`
    — see `resolve_items`'s own `search_name` for why this isn't always the item's
    canonical name. `candidates` is one retailer's own deduped candidate list (CP9
    follow-up, 2026-08-08 — previously a cross-retailer merged set; ambiguity is now
    judged independently per retailer, see `make_resolve_items` below). Returns
    (resolved_label_or_None, still_ambiguous, effective_candidates) — the third element is
    the candidate list this decision was actually made against (unchanged unless relevance
    filtering ran), which the caller persists back into `item_candidates` so
    resolve_ambiguity.py's later display reflects the same filtering, not the raw DB
    results. A resolved label is a product name used as the search query in that same
    retailer's own catalog later — not an item_code."""
    if not candidates:
        return search_name, False, candidates  # nothing matched anywhere; let per-retailer building report it missing
    if len(candidates) == 1:
        return candidates[0]["name"], False, candidates

    exact = [c for c in candidates if c["name"].strip().lower() == search_name.strip().lower()]
    if len(exact) == 1:
        return exact[0]["name"], False, candidates

    if brand_preference:
        matches = [c for c in candidates if brand_preference.strip().lower() in c["name"].strip().lower()]
        if len(matches) == 1:
            return matches[0]["name"], False, candidates

    # A plain ILIKE substring search has no relevance ranking at all — it routinely
    # returns products where search_name only matches as a flavor/ingredient/appliance
    # descriptor of a genuinely different product (e.g. a rice-cooker for "rice"). Only
    # reached once the cheap deterministic rules above fail to resolve unambiguously.
    relevant = await filter_relevant_candidates(llm, search_name, candidates)
    if not relevant:
        return search_name, False, relevant  # LLM judged none of these the right product — treat as a miss
    if len(relevant) == 1:
        return relevant[0]["name"], False, relevant

    # 2+ genuinely relevant candidates remain (e.g. several real rice/tuna/milk
    # products) — the relevance filter's job ends at "is this actually relevant", not
    # "which one should the user buy" (2026-08-14 fix: `cheapest` used to run *before*
    # relevance filtering, so it could silently win on a raw, unfiltered candidate;
    # applying it here means it now only ever picks among candidates already confirmed
    # relevant). Without an explicit cheapest preference, this is real ambiguity — the
    # user chooses. `MAX_CANDIDATES_SHOWN` caps the *returned/displayed* shortlist only;
    # the ambiguity decision itself already happened above, against the full relevant
    # set, not this truncated view.
    if selection_preference == "cheapest":
        return min(relevant, key=lambda c: c["price"])["name"], False, relevant

    shortlist = sorted(relevant, key=lambda c: c["price"])[:MAX_CANDIDATES_SHOWN]
    return None, True, shortlist


def make_resolve_items(client, llm):
    async def resolve_items(state: AgentState) -> AgentState:
        parsed = state["parsed_request"]
        item_candidates = dict(state.get("item_candidates", {}))
        # item name -> retailer -> resolved product name (CP9 follow-up, 2026-08-08 —
        # previously item name -> a single label shared across every retailer, which
        # broke whichever retailer's own catalog didn't happen to contain that exact
        # text; see resolve_ambiguity.py and build_retailer_cart.py for the other two
        # places this per-retailer shape now flows through).
        resolved_choices = {k: dict(v) for k, v in state.get("resolved_choices", {}).items()}
        dietary_conflicts = list(state.get("dietary_conflicts", []))
        ambiguous_item = None
        forbidden = forbidden_tags(parsed.get("dietary_constraints", []))

        for item in parsed["items"]:
            name = item["name"]
            if name in dietary_conflicts:
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

            if not any(by_retailer.values()) and forbidden:
                sub_query = find_substitute_query(name, forbidden)
                if sub_query is None:
                    dietary_conflicts.append(name)
                    continue
                by_retailer = await _candidates_by_retailer(client, sub_query, forbidden)
                item_candidates[name] = by_retailer

            # Ambiguity is judged, and resolved, independently per retailer — a retailer
            # with exactly one candidate auto-resolves immediately without ever asking;
            # only a retailer that's genuinely ambiguous on its own candidates blocks on
            # the user, and it doesn't hold up any other retailer that already resolved.
            item_resolved = dict(resolved_choices.get(name, {}))
            still_ambiguous_here = False
            for retailer, candidates in by_retailer.items():
                if retailer in item_resolved or not candidates:
                    # Already resolved, or nothing found at all for this retailer — the
                    # latter isn't ambiguity, just a miss; build_retailer_cart.py's own
                    # search_name fallback covers it when no entry exists here.
                    continue
                label, still_ambiguous, effective_candidates = await _resolve_item(
                    llm, search_name, _dedupe_by_name(candidates),
                    parsed.get("brand_preference"), parsed.get("selection_preference", "no_preference"),
                )
                # Persisted so resolve_ambiguity.py's later display reflects relevance
                # filtering too, not just this function's own resolve/still-ambiguous
                # decision — it independently re-reads item_candidates from state.
                by_retailer[retailer] = effective_candidates
                if label is not None:
                    item_resolved[retailer] = label
                elif still_ambiguous:
                    still_ambiguous_here = True

            if item_resolved:
                resolved_choices[name] = item_resolved
            if still_ambiguous_here and ambiguous_item is None:
                ambiguous_item = name

        return {
            "item_candidates": item_candidates,
            "resolved_choices": resolved_choices,
            "pending_clarification_item": ambiguous_item,
            "dietary_conflicts": dietary_conflicts,
        }

    return resolve_items
