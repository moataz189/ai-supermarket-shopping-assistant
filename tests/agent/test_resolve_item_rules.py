from app.agent.nodes.resolve_items import _resolve_item


async def test_single_candidate_auto_resolves():
    candidates = [{"item_code": "S1", "name": "Kiwi", "price": 3.0}]

    label, still_ambiguous = await _resolve_item("kiwi", candidates, None, "no_preference")

    assert label == "Kiwi"
    assert still_ambiguous is False


async def test_exact_name_match_auto_resolves():
    candidates = [
        {"item_code": "S1", "name": "milk", "price": 5.0},
        {"item_code": "S2", "name": "Chocolate Milk", "price": 6.0},
    ]

    label, still_ambiguous = await _resolve_item("milk", candidates, None, "no_preference")

    assert label == "milk"
    assert still_ambiguous is False


async def test_brand_preference_auto_resolves():
    candidates = [
        {"item_code": "S1", "name": "Tnuva Butter", "price": 5.0},
        {"item_code": "S2", "name": "Tara Butter", "price": 5.5},
    ]

    label, still_ambiguous = await _resolve_item("butter", candidates, "Tnuva", "no_preference")

    assert label == "Tnuva Butter"
    assert still_ambiguous is False


async def test_cheapest_preference_auto_resolves():
    candidates = [
        {"item_code": "S1", "name": "Tnuva Butter", "price": 5.5},
        {"item_code": "S2", "name": "Tara Butter", "price": 5.0},
    ]

    label, still_ambiguous = await _resolve_item("butter", candidates, None, "cheapest")

    assert label == "Tara Butter"
    assert still_ambiguous is False


async def test_no_matching_rule_stays_ambiguous():
    candidates = [
        {"item_code": "S1", "name": "Tnuva Butter", "price": 5.0},
        {"item_code": "S2", "name": "Tara Butter", "price": 5.5},
        {"item_code": "S3", "name": "President Butter", "price": 6.0},
    ]

    label, still_ambiguous = await _resolve_item("butter", candidates, None, "no_preference")

    assert label is None
    assert still_ambiguous is True


async def test_no_candidates_returns_name_unambiguous():
    label, still_ambiguous = await _resolve_item("unobtainium", [], None, "no_preference")

    assert label == "unobtainium"
    assert still_ambiguous is False
