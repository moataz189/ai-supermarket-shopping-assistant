from app.agent.nodes.resolve_items import MAX_CANDIDATES_SHOWN, _dedupe_by_name, _resolve_item
from tests.agent.fakes import FakeLLM


async def test_single_candidate_auto_resolves():
    candidates = [{"item_code": "S1", "name": "Kiwi", "price": 3.0}]

    label, still_ambiguous, effective = await _resolve_item(FakeLLM(), "kiwi", candidates, None, "no_preference")

    assert label == "Kiwi"
    assert still_ambiguous is False
    assert effective == candidates


async def test_exact_name_match_auto_resolves():
    candidates = [
        {"item_code": "S1", "name": "milk", "price": 5.0},
        {"item_code": "S2", "name": "Chocolate Milk", "price": 6.0},
    ]

    label, still_ambiguous, effective = await _resolve_item(FakeLLM(), "milk", candidates, None, "no_preference")

    assert label == "milk"
    assert still_ambiguous is False
    assert effective == candidates


async def test_brand_preference_auto_resolves():
    candidates = [
        {"item_code": "S1", "name": "Tnuva Butter", "price": 5.0},
        {"item_code": "S2", "name": "Tara Butter", "price": 5.5},
    ]

    label, still_ambiguous, effective = await _resolve_item(
        FakeLLM(), "butter", candidates, "Tnuva", "no_preference"
    )

    assert label == "Tnuva Butter"
    assert still_ambiguous is False
    assert effective == candidates


async def test_cheapest_preference_auto_resolves():
    candidates = [
        {"item_code": "S1", "name": "Tnuva Butter", "price": 5.5},
        {"item_code": "S2", "name": "Tara Butter", "price": 5.0},
    ]

    label, still_ambiguous, effective = await _resolve_item(FakeLLM(), "butter", candidates, None, "cheapest")

    assert label == "Tara Butter"
    assert still_ambiguous is False
    assert effective == candidates


async def test_no_matching_rule_stays_ambiguous():
    # No relevance filtering configured on the FakeLLM (relevant_names=None) — every
    # candidate name is echoed back as relevant, a no-op equivalent to the pre-relevance-
    # filtering behavior this test originally covered.
    candidates = [
        {"item_code": "S1", "name": "Tnuva Butter", "price": 5.0},
        {"item_code": "S2", "name": "Tara Butter", "price": 5.5},
        {"item_code": "S3", "name": "President Butter", "price": 6.0},
    ]

    label, still_ambiguous, effective = await _resolve_item(FakeLLM(), "butter", candidates, None, "no_preference")

    assert label is None
    assert still_ambiguous is True
    assert effective == candidates


async def test_no_candidates_returns_name_unambiguous():
    label, still_ambiguous, effective = await _resolve_item(FakeLLM(), "unobtainium", [], None, "no_preference")

    assert label == "unobtainium"
    assert still_ambiguous is False
    assert effective == []


async def test_relevance_filtering_drops_appliance_and_auto_resolves_to_sole_food_match():
    # Real example this was built for: an ILIKE search for "אורז" (rice) also returns a
    # "rice cooker" appliance, which merely mentions rice, not a rice product itself.
    candidates = [
        {"item_code": "S1", "name": "אורז בסמטי 1 קג", "price": 8.0},
        {"item_code": "S2", "name": "אורז מולטי קוקר", "price": 250.0},
    ]
    llm = FakeLLM(relevant_names=["אורז בסמטי 1 קג"])

    label, still_ambiguous, effective = await _resolve_item(llm, "אורז", candidates, None, "no_preference")

    assert label == "אורז בסמטי 1 קג"
    assert still_ambiguous is False
    assert effective == [candidates[0]]


async def test_relevance_filtering_narrows_ambiguity_to_only_relevant_candidates():
    candidates = [
        {"item_code": "S1", "name": "Tnuva Milk 3%", "price": 6.0},
        {"item_code": "S2", "name": "Tara Milk 1%", "price": 5.5},
        {"item_code": "S3", "name": "Milk Chocolate Bar", "price": 7.0},
    ]
    llm = FakeLLM(relevant_names=["Tnuva Milk 3%", "Tara Milk 1%"])

    label, still_ambiguous, effective = await _resolve_item(llm, "milk", candidates, None, "no_preference")

    assert label is None
    assert still_ambiguous is True
    # Displayed shortlist is cheapest-first (2026-08-14 fix) -- Tara (5.5) before
    # Tnuva (6.0), not raw candidate-list order.
    assert effective == [candidates[1], candidates[0]]


async def test_relevance_filtering_to_zero_relevant_is_treated_as_a_miss_not_a_crash():
    # Two candidates, both irrelevant — len(candidates) == 1 would auto-resolve before
    # relevance filtering ever runs, so this needs at least two to actually exercise it.
    candidates = [
        {"item_code": "S1", "name": "Donut Milk Flavor Pack", "price": 12.0},
        {"item_code": "S2", "name": "Milk Chocolate Bar", "price": 7.0},
    ]
    llm = FakeLLM(relevant_names=[])

    label, still_ambiguous, effective = await _resolve_item(llm, "milk", candidates, None, "no_preference")

    assert label == "milk"
    assert still_ambiguous is False
    assert effective == []


async def test_relevance_filtering_matches_names_case_insensitively():
    # The LLM echoes back product names verbatim from its own generation, which is not
    # guaranteed to preserve the candidate dict's exact casing (e.g. "Basmati Rice" vs.
    # the catalog's stored "basmati rice") — a casing-only mismatch must still match, not
    # silently degrade to "no candidates relevant".
    candidates = [
        {"item_code": "S1", "name": "basmati rice", "price": 8.0},
        {"item_code": "S2", "name": "rice cooker", "price": 250.0},
    ]
    llm = FakeLLM(relevant_names=["Basmati Rice"])

    label, still_ambiguous, _effective = await _resolve_item(llm, "rice", candidates, None, "no_preference")

    assert label == "basmati rice"
    assert still_ambiguous is False


# ---------------------------------------------------------------------------
# Fix 1 (2026-08-14): MAX_CANDIDATES_SHOWN is a display limit only -- it must never gate
# what reaches semantic relevance filtering, nor the ambiguity decision itself. Real user
# report: a display-sized cap applied *before* relevance filtering lost genuinely
# relevant products (real milk, enough pasta options, several real rice/tuna products)
# that happened to sit past the first few raw DB results.
# ---------------------------------------------------------------------------


def test_dedupe_by_name_does_not_truncate():
    # 8 uniquely-named candidates -- well past the old cap of 5 -- must all survive
    # deduping. Truncation (if any) belongs downstream, after relevance filtering.
    candidates = [{"item_code": f"S{i}", "name": f"Product {i}", "price": float(i)} for i in range(8)]

    result = _dedupe_by_name(candidates)

    assert len(result) == 8


async def test_a_relevant_candidate_past_the_old_cap_of_five_still_survives():
    # 7 raw candidates for "milk" -- more than the old MAX_CANDIDATES_SHOWN=5 -- where
    # the one genuine milk product is deliberately placed *last*. Under the old
    # (pre-2026-08-14) behavior, _dedupe_by_name's cap would have dropped it before
    # relevance filtering ever ran, producing a false "not_found" even though a real
    # match existed in the full candidate pool.
    candidates = [
        {"item_code": f"S{i}", "name": f"Milk Chocolate Bar {i}", "price": 7.0 + i}
        for i in range(6)
    ] + [{"item_code": "S-REAL", "name": "Tnuva Milk 3%", "price": 6.0}]
    llm = FakeLLM(relevant_names=["Tnuva Milk 3%"])

    label, still_ambiguous, _effective = await _resolve_item(llm, "milk", candidates, None, "no_preference")

    assert label == "Tnuva Milk 3%"
    assert still_ambiguous is False


async def test_ten_plus_relevant_candidates_still_shows_only_max_candidates_shown():
    # The *decision* to ask (still_ambiguous=True) must be based on the full relevant
    # set, but only MAX_CANDIDATES_SHOWN are actually returned for display.
    candidates = [{"item_code": f"S{i}", "name": f"Rice Type {i}", "price": float(20 - i)} for i in range(10)]
    llm = FakeLLM(relevant_names=[c["name"] for c in candidates])  # all 10 relevant

    label, still_ambiguous, effective = await _resolve_item(llm, "rice", candidates, None, "no_preference")

    assert label is None
    assert still_ambiguous is True
    assert len(effective) == MAX_CANDIDATES_SHOWN


# ---------------------------------------------------------------------------
# Fix 3 (2026-08-14): the relevance filter answers "is this relevant", not "which one
# should the user buy". `cheapest` now runs *after* relevance filtering (picks among
# confirmed-relevant candidates only), and without an explicit cheapest preference, 2+
# relevant candidates is real ambiguity the user must resolve -- min(price) must never
# silently pick for them by default.
# ---------------------------------------------------------------------------


async def test_multiple_relevant_candidates_without_cheapest_preference_stays_ambiguous():
    # Real user report: "chillies" judged both a fresh and a packaged/preserved hot
    # pepper product relevant, and the system silently picked the cheaper one instead of
    # asking. Without an explicit cheapest preference, this must be real ambiguity.
    candidates = [
        {"item_code": "S1", "name": "Fresh Chili Pepper", "price": 12.9},
        {"item_code": "S2", "name": "Preserved Chili Pepper 225g", "price": 13.56},
    ]
    llm = FakeLLM(relevant_names=["Fresh Chili Pepper", "Preserved Chili Pepper 225g"])

    label, still_ambiguous, effective = await _resolve_item(llm, "chillies", candidates, None, "no_preference")

    assert label is None
    assert still_ambiguous is True
    assert {c["item_code"] for c in effective} == {"S1", "S2"}


async def test_cheapest_preference_picks_among_relevant_candidates_not_raw_candidates():
    # The cheapest RAW candidate (a rice cooker) is not actually rice at all -- cheapest
    # must never win by being cheap alone; it only ever picks among candidates the
    # relevance filter already confirmed are genuinely relevant.
    candidates = [
        {"item_code": "S1", "name": "Rice Cooker Appliance", "price": 5.0},  # cheapest raw, but irrelevant
        {"item_code": "S2", "name": "Basmati Rice", "price": 12.0},
        {"item_code": "S3", "name": "Jasmine Rice", "price": 10.0},
    ]
    llm = FakeLLM(relevant_names=["Basmati Rice", "Jasmine Rice"])

    label, still_ambiguous, effective = await _resolve_item(llm, "rice", candidates, None, "cheapest")

    assert label == "Jasmine Rice"  # cheapest of the two RELEVANT candidates, not the raw cooker
    assert still_ambiguous is False
    assert {c["item_code"] for c in effective} == {"S2", "S3"}  # the raw cooker never enters the result
