import asyncio
import math

from app.agent.nodes.product_relevance import filter_relevant_candidates
from app.agent.state import AgentState
from app.dietary.rules import find_substitute_query, forbidden_tags, tags_for_name

RETAILERS = ["shufersal", "rami_levy"]

# Chicken breast is only orderable in whole-kilogram increments for both retailers in
# the currently supported flow -- real user report (2026-08-16): a fractional kg
# request (e.g. the weekly-shop "one_person" profile's real 0.4 kg serving size) priced
# the comparison view at 0.4 kg while the real Retailer-Cart MCP add would buy a whole
# kg regardless, so the displayed price/quantity and what actually got bought disagreed.
# Deliberately scoped to this one item by explicit product decision -- NOT a general
# kg-rounding rule: loose "tomato" at 0.5 kg must stay fractional, since fractional
# weight genuinely works for that product; only chicken breast has this whole-kg-only
# constraint. Matched by name (both the Hebrew weekly-shop-profile name and the English
# recipe-ingredient name), not by unit, since this is a per-product retailer constraint,
# not a general quantity-classification rule (contrast with app/agent/quantity.py,
# which classifies by unit string alone and explicitly avoids per-product rules).
_WHOLE_KG_ONLY_ITEMS = {"חזה עוף", "chicken breast"}


def _normalize_quantity(item: dict) -> dict:
    """Rounds a whole-kg-only item's requested kg quantity UP to the next whole
    kilogram (0 < x <= 1 -> 1, 1 < x <= 2 -> 2, ...) -- see _WHOLE_KG_ONLY_ITEMS. Applied
    once, here, before any pricing/budget/payload logic ever reads `item["quantity"]`,
    so the normalized value is the single source of truth for the comparison-view
    price, the cart total, the budget check, the Retailer-Cart MCP payload, and the
    final "Requested/Added" result -- all of which only ever copy this same field
    forward, never re-derive it independently. Every other item (including a whole-kg
    chicken-breast request already at 1.0/2.0/... kg) passes through unchanged."""
    name = (item.get("name") or "").strip().lower()
    quantity, unit = item.get("quantity"), item.get("unit")
    if name in _WHOLE_KG_ONLY_ITEMS and unit == "kg" and quantity is not None and quantity > 0:
        return {**item, "quantity": float(math.ceil(quantity))}
    return item

# A DISPLAY limit only (2026-08-14 fix) -- how many relevant candidates to show the user
# in the ambiguity UI when there's a real choice to make. Must never gate what reaches
# semantic relevance filtering or the ambiguity decision itself (still_ambiguous is
# always based on the *full* relevant set) -- conflating the two caused genuinely
# relevant products (real milk, enough pasta options, multiple real rice/tuna products)
# to be silently lost before the relevance filter ever saw them.
MAX_CANDIDATES_SHOWN = 5

# Explicit item_code overrides for a specific (ingredient, retailer) pair, bypassing
# catalog search entirely -- real user report (2026-08-16): "pasta shells" at Shufersal
# kept failing through several general search/translation fixes in a row (the mandatory
# second word, the fused weight suffix, Hebrew singular/plural) because the real live
# product name ("ניוקטי סרדי קונכיה500גר") doesn't reliably match any general
# translation. By explicit user decision, this one case is pinned directly to its real
# item_code rather than another attempt at a general search fix -- the price is still
# fetched live (see _override_candidates), only the search/matching step is skipped.
_KNOWN_ITEM_OVERRIDES: dict[tuple[str, str], tuple[str, str]] = {
    ("pasta shells", "shufersal"): ("8008912010331", "ניוקטי סרדי קונכיה500גר"),
}


async def _override_candidates(client, retailer: str, item_code: str, name: str) -> list[dict]:
    price_info = await client.get_product_price(retailer, item_code)
    if price_info is None:
        return []
    return [{"item_code": item_code, "name": name, "price": price_info["price"]}]


async def _candidates_by_retailer(
    client, name: str, forbidden: set[str], item_name: str | None = None
) -> dict[str, list[dict]]:
    """Keeps each retailer's candidates separate — never merged away — so the user can
    see which retailer actually carries which option before choosing (spec §3). Candidates
    that violate `forbidden` dietary tags are filtered out here too, so a filtered-out option
    never appears in the per-retailer breakdown shown to the user (CP7).

    `item_name` (the item's own canonical name, distinct from `name` -- the already-
    localized search term) is only used to check `_KNOWN_ITEM_OVERRIDES`; a retailer
    with a known override skips client.search_product entirely for that retailer."""
    result = {}
    for retailer in RETAILERS:
        override = _KNOWN_ITEM_OVERRIDES.get((item_name, retailer))
        if override is not None:
            item_code, override_name = override
            candidates = await _override_candidates(client, retailer, item_code, override_name)
        else:
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
        parsed = dict(state["parsed_request"])
        parsed["items"] = [_normalize_quantity(item) for item in parsed["items"]]
        item_candidates = dict(state.get("item_candidates", {}))
        # item name -> retailer -> resolved product name (CP9 follow-up, 2026-08-08 —
        # previously item name -> a single label shared across every retailer, which
        # broke whichever retailer's own catalog didn't happen to contain that exact
        # text; see resolve_ambiguity.py and build_retailer_cart.py for the other two
        # places this per-retailer shape now flows through).
        resolved_choices = {k: dict(v) for k, v in state.get("resolved_choices", {}).items()}
        dietary_conflicts = list(state.get("dietary_conflicts", []))
        forbidden = forbidden_tags(parsed.get("dietary_constraints", []))

        # Every item's own candidate search, dietary substitution, and relevance-filter
        # decision is fully independent of every other item's (and, within an item,
        # independent per retailer) -- real user report (2026-08-15): a 6-item recipe
        # across 2 retailers made up to 12 sequential relevance-filter LLM calls, each a
        # real network round trip, confirmed live to take tens of seconds. Below runs
        # each phase concurrently (asyncio.gather) instead of one item/retailer at a
        # time; the actual item_candidates/resolved_choices/dietary_conflicts merge
        # still happens in a single-threaded pass afterwards, in the original list
        # order, so which item becomes `pending_clarification_item` and every other
        # observable outcome is unchanged -- only wall-clock time improves.
        items = [item for item in parsed["items"] if item["name"] not in dietary_conflicts]
        # Recipe-derived items carry an English canonical `name` (Spoonacular) and a
        # `search_name` that's *always* tried in Hebrew when a translation exists (see
        # get_recipe_ingredients.py) — the real catalog is Hebrew-only regardless of
        # what language this conversation is in, so searching with the English name
        # never matches even when the equivalent product genuinely exists (confirmed
        # live, twice: once for a Hebrew-language conversation, then again for an
        # English one — `display_name` alone isn't enough, since it follows the
        # conversation's own language and stays English there). Grocery-list items have
        # no search_name/display_name at all (already typed in the user's own
        # language), so this is a no-op fallback for them.
        search_names = {
            item["name"]: item.get("search_name") or item.get("display_name") or item["name"]
            for item in items
        }

        to_search = [item["name"] for item in items if item["name"] not in item_candidates]
        if to_search:
            searched = await asyncio.gather(*(
                _candidates_by_retailer(client, search_names[name], forbidden, item_name=name)
                for name in to_search
            ))
            for name, by_retailer in zip(to_search, searched, strict=True):
                item_candidates[name] = by_retailer

        # A retailer-wide miss under a dietary constraint retries with a substitute
        # query — also independent per item.
        needs_substitute = [
            item["name"] for item in items
            if forbidden and not any(item_candidates[item["name"]].values())
        ]
        substitute_queries = {name: find_substitute_query(name, forbidden) for name in needs_substitute}
        to_resubstitute = [name for name in needs_substitute if substitute_queries[name] is not None]
        if to_resubstitute:
            resubstituted = await asyncio.gather(
                *(_candidates_by_retailer(client, substitute_queries[name], forbidden) for name in to_resubstitute)
            )
            for name, by_retailer in zip(to_resubstitute, resubstituted, strict=True):
                item_candidates[name] = by_retailer
        for name in needs_substitute:
            if substitute_queries[name] is None:
                dietary_conflicts.append(name)

        # Ambiguity is judged, and resolved, independently per retailer — a retailer
        # with exactly one candidate auto-resolves immediately without ever asking;
        # only a retailer that's genuinely ambiguous on its own candidates blocks on
        # the user, and it doesn't hold up any other retailer that already resolved.
        remaining_items = [item for item in items if item["name"] not in dietary_conflicts]
        pending: list[tuple[str, str]] = []
        for item in remaining_items:
            name = item["name"]
            item_resolved = resolved_choices.get(name, {})
            for retailer, candidates in item_candidates[name].items():
                if retailer in item_resolved or not candidates:
                    # Already resolved, or nothing found at all for this retailer — the
                    # latter isn't ambiguity, just a miss; build_retailer_cart.py's own
                    # search_name fallback covers it when no entry exists here.
                    continue
                pending.append((name, retailer))

        outcomes = {}
        if pending:
            results = await asyncio.gather(*(
                _resolve_item(
                    llm, search_names[name], _dedupe_by_name(item_candidates[name][retailer]),
                    parsed.get("brand_preference"), parsed.get("selection_preference", "no_preference"),
                )
                for name, retailer in pending
            ))
            outcomes = dict(zip(pending, results, strict=True))

        ambiguous_item = None
        for item in remaining_items:
            name = item["name"]
            by_retailer = item_candidates[name]
            item_resolved = dict(resolved_choices.get(name, {}))
            still_ambiguous_here = False
            for retailer in by_retailer:
                if (name, retailer) not in outcomes:
                    continue
                label, still_ambiguous, effective_candidates = outcomes[(name, retailer)]
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
            "parsed_request": parsed,
            "item_candidates": item_candidates,
            "resolved_choices": resolved_choices,
            "pending_clarification_item": ambiguous_item,
            "dietary_conflicts": dietary_conflicts,
        }

    return resolve_items
