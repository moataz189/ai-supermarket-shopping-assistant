from app.agent.nodes.resolve_items import _resolve_item
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
    assert effective == candidates[:2]


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

    label, still_ambiguous, effective = await _resolve_item(llm, "rice", candidates, None, "no_preference")

    assert label == "basmati rice"
    assert still_ambiguous is False
    assert effective == [candidates[0]]
