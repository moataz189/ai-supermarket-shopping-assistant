from app.agent.nodes.finalize import finalize


def _state(cart: dict) -> dict:
    return {
        "retailer_carts": {"shufersal": cart},
        "chosen_retailer": None,
        "retailer_cart_result": None,
    }


def _cart(**overrides) -> dict:
    base = {
        "retailer": "shufersal", "items": [], "missing_items": [], "total": 0.0,
        "budget": None, "allowed_max": None, "over_budget_by": None,
        "no_items_fit_budget": False, "trade_off_suggestions": [],
    }
    base.update(overrides)
    return base


def test_no_warning_when_within_the_10_percent_tolerance():
    cart = _cart(total=102.0, budget=100.0, allowed_max=110.0, over_budget_by=2.0)
    result = finalize(_state(cart))
    codes = {w["code"] for w in result["warnings"]}
    assert "budget_exceeded" not in codes
    assert result["status"] == "success"


def test_warning_when_truly_over_the_10_percent_tolerance():
    cart = _cart(total=115.0, budget=100.0, allowed_max=110.0, over_budget_by=15.0)
    result = finalize(_state(cart))
    warning = next(w for w in result["warnings"] if w["code"] == "budget_exceeded")
    assert warning["retailer"] == "shufersal"
    assert warning["over_budget_by"] == 15.0
    assert result["status"] == "partial_success"


def test_no_items_within_budget_warning_prevents_successful_empty_cart():
    cart = _cart(total=0.0, budget=20.0, allowed_max=22.0, no_items_fit_budget=True)
    result = finalize(_state(cart))
    codes = {w["code"] for w in result["warnings"]}
    assert "no_items_within_budget" in codes
    assert result["status"] == "partial_success"
