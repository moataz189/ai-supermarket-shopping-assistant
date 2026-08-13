"""Unit tests for ShufersalAdapter's fetch/ajaxCall-based logic, against a fake `page`
that never touches a real browser or the real site. No DOM locator behavior is exercised
here (this adapter doesn't use one) — these tests pin down search-result matching,
add-to-cart confirmation via a fresh search round trip, and the unsupported_site_flow
fallback when the internal `window.ajaxCall` interface isn't available.
"""

import pytest

from mcp_servers.retailer_cart_mcp.adapters.shufersal import ShufersalAdapter
from mcp_servers.retailer_cart_mcp.automation import (
    MatchResult,
    QuantityNotConfirmedError,
    UnsupportedSiteFlowError,
)
from mcp_servers.retailer_cart_mcp.quantity import QuantityConversionRequiredError


class _EmptyLocator:
    async def count(self):
        return 0


class FakePage:
    def __init__(self, *, ajax_call_exists=True, search_results=None, add_raises=None):
        self.ajax_call_exists = ajax_call_exists
        # queue of result-lists returned by successive `_search` calls
        self._search_results = list(search_results) if search_results is not None else []
        self.add_raises = add_raises
        self.add_calls = []
        self.search_urls = []

    async def goto(self, url):
        pass

    async def content(self):
        return "<html></html>"

    def locator(self, selector):
        return _EmptyLocator()

    async def evaluate(self, script, arg=None):
        if "typeof window.ajaxCall" in script:
            return self.ajax_call_exists
        if "window.ajaxCall('/cart/add'" in script:
            self.add_calls.append(arg)
            if self.add_raises:
                raise self.add_raises
            return None
        if "fetch(url" in script:
            self.search_urls.append(arg)
            if not self._search_results:
                raise AssertionError("no more scripted search responses")
            return self._search_results.pop(0)
        raise AssertionError(f"unexpected script: {script}")


def _ok(results):
    return {"ok": True, "results": results}


async def test_search_and_match_exact_name_match():
    # item_code="" (falsy) — no code to search by, exercises the pure name-matching path.
    page = FakePage(search_results=[_ok([
        {"code": "P1", "name": "Milk", "sellingMethod": {"code": "BY_UNIT"}, "cartStatus": {}},
    ])])

    match = await ShufersalAdapter().search_and_match(page, "Milk", "")

    assert match.item_code == "P1"
    assert match.matched_by == "exact_name"


async def test_search_and_match_case_insensitive_exact_match():
    page = FakePage(search_results=[_ok([
        {"code": "P1", "name": "MILK 3%", "sellingMethod": {"code": "BY_UNIT"}, "cartStatus": {}},
    ])])

    match = await ShufersalAdapter().search_and_match(page, "milk 3%", "")

    assert match.matched_by == "exact_name"


async def test_search_and_match_returns_none_when_no_exact_name_match():
    # The "just take the first search result" fallback was removed (CP9 follow-up,
    # 2026-08-08) after it added a real, wrong product to a real cart live — a search hit
    # with no exact name match must be reported honestly as unmatched, not guessed at.
    page = FakePage(search_results=[_ok([
        {
            "code": "P2",
            "name": "Something Else",
            "sellingMethod": {"code": "BY_UNIT"},
            "cartStatus": {},
        },
    ])])

    match = await ShufersalAdapter().search_and_match(page, "Milk", "")

    assert match is None


async def test_search_and_match_finds_by_code_search_alone_without_a_name_search():
    # confirmed live: querying the bare numeric code directly returns exactly the right
    # product — this must resolve from the code search alone, never touching the name
    # search at all (only one response queued; a second _search call would raise).
    page = FakePage(search_results=[_ok([
        {"code": "P_123", "name": "Ice Cream", "sellingMethod": {"code": "BY_UNIT"}, "cartStatus": {}},
    ])])

    match = await ShufersalAdapter().search_and_match(page, "Ice Cream 1kg BRAND", "123")

    assert match.item_code == "P_123"
    assert match.matched_by == "item_code"


async def test_search_and_match_code_search_query_strips_p_prefix():
    page = FakePage(search_results=[_ok([
        {"code": "P_123", "name": "Something Unrelated", "sellingMethod": {"code": "BY_UNIT"}, "cartStatus": {}},
    ])])

    match = await ShufersalAdapter().search_and_match(page, "Ice Cream", "P_123")

    assert match.item_code == "P_123"
    assert match.matched_by == "item_code"
    assert page.search_urls[0].endswith("q=123&limit=20")  # not "P_123"


async def test_search_and_match_disambiguates_same_name_products_by_code():
    # confirmed live: a name search for a generic product name can return several
    # genuinely different products sharing the exact same display name — code must pick
    # out the right one even when the first (or any) name match would otherwise "look"
    # like a valid exact_name hit.
    page = FakePage(search_results=[_ok([
        {"code": "P_100", "name": "לחם אחיד פרוס", "sellingMethod": {"code": "BY_UNIT"}, "cartStatus": {}},
    ])])

    match = await ShufersalAdapter().search_and_match(page, "לחם אחיד פרוס", "100")

    assert match.item_code == "P_100"
    assert match.matched_by == "item_code"


async def test_search_and_match_falls_back_to_name_when_code_search_finds_nothing():
    page = FakePage(search_results=[
        _ok([{"code": "P9", "name": "Unrelated", "sellingMethod": {"code": "BY_UNIT"}, "cartStatus": {}}]),
        _ok([{"code": "P1", "name": "Milk", "sellingMethod": {"code": "BY_UNIT"}, "cartStatus": {}}]),
    ])

    match = await ShufersalAdapter().search_and_match(page, "Milk", "999-not-present")

    assert match.item_code == "P1"
    assert match.matched_by == "exact_name"


async def test_search_and_match_falls_back_to_legacy_short_code_when_full_barcode_finds_nothing():
    # confirmed live (2026-08-13): Shufersal's search index is inconsistent -- some
    # products' internal code equals the full 13-digit GTIN as-is, others use a legacy
    # short code (the GTIN with its 3-digit GS1 country prefix and leading zeros
    # stripped). Barcode 7290000060781 finds nothing searched as-is, but "60781" (its
    # short form) finds the exact same product. Confirmed safe: a stripped form of a
    # DIFFERENT, already-matching barcode found zero results rather than colliding with
    # an unrelated product -- so this is a second EXACT-code attempt, not a name/fuzzy
    # guess, and doesn't reopen the "guessed the wrong product" failure mode.
    page = FakePage(search_results=[
        _ok([]),  # full 13-digit barcode search finds nothing
        _ok([{"code": "P_60781", "name": "פסטה מסולסלת", "sellingMethod": {"code": "BY_UNIT"}, "cartStatus": {}}]),
    ])

    match = await ShufersalAdapter().search_and_match(page, "פסטה", "7290000060781")

    assert match.item_code == "P_60781"
    assert match.matched_by == "item_code"
    assert page.search_urls[0].endswith("q=7290000060781&limit=20")
    assert page.search_urls[1].endswith("q=60781&limit=20")


async def test_search_and_match_short_code_fallback_not_tried_for_non_13_digit_codes():
    # The short-code transform only makes sense for a full-length GTIN -- a shorter code
    # (already the legacy form, or just not a barcode) must not trigger a second search
    # attempt. Only one response is queued; a second _search call would raise.
    page = FakePage(search_results=[_ok([]), _ok([{"code": "P1", "name": "Milk", "sellingMethod": {"code": "BY_UNIT"}, "cartStatus": {}}])])

    match = await ShufersalAdapter().search_and_match(page, "Milk", "60781")

    # Falls through to the ordinary name search (2nd queued response), not a short-code retry.
    assert match.item_code == "P1"
    assert match.matched_by == "exact_name"


async def test_search_and_match_skips_short_code_retry_when_full_code_already_matches():
    # A successful full-code match must not trigger any further search call -- only one
    # response is queued; a second _search call would raise.
    page = FakePage(search_results=[
        _ok([{"code": "P_7290000060781", "name": "פסטה מסולסלת", "sellingMethod": {"code": "BY_UNIT"}, "cartStatus": {}}]),
    ])

    match = await ShufersalAdapter().search_and_match(page, "פסטה", "7290000060781")

    assert match.item_code == "P_7290000060781"
    assert match.matched_by == "item_code"


async def test_search_and_match_returns_none_when_no_results_by_code_or_name():
    page = FakePage(search_results=[_ok([]), _ok([])])

    match = await ShufersalAdapter().search_and_match(page, "Milk", "ignored-code")

    assert match is None


async def test_search_and_match_returns_none_when_no_results_and_no_code():
    page = FakePage(search_results=[_ok([])])

    match = await ShufersalAdapter().search_and_match(page, "Milk", "")

    assert match is None


async def test_search_raises_unsupported_site_flow_on_non_ok_status():
    page = FakePage(search_results=[{"ok": False, "status": 500}])

    with pytest.raises(UnsupportedSiteFlowError):
        await ShufersalAdapter().search_and_match(page, "Milk", "ignored-code")


async def test_add_to_cart_confirms_via_fresh_search_round_trip():
    match = MatchResult(
        item_code="P1",
        locator={"code": "P1", "name": "Milk", "sellingMethod": {"code": "BY_UNIT"}},
        matched_by="exact_name",
    )
    page = FakePage(search_results=[_ok([
        {"code": "P1", "name": "Milk", "cartStatus": {"inCart": True, "qty": 2}},
    ])])

    result = await ShufersalAdapter().add_to_cart(page, match, 2)

    assert result.quantity == 2
    assert result.unit == "unit"
    assert page.add_calls == [{"productCode": "P1", "sellingMethod": "BY_UNIT", "qty": 2}]


async def test_add_to_cart_raises_quantity_not_confirmed_on_mismatch():
    match = MatchResult(
        item_code="P1",
        locator={"code": "P1", "name": "Milk", "sellingMethod": {"code": "BY_UNIT"}},
        matched_by="exact_name",
    )
    # site's own cartStatus disagrees with what was requested (e.g. a stock cap)
    page = FakePage(search_results=[_ok([
        {"code": "P1", "name": "Milk", "cartStatus": {"inCart": True, "qty": 1}},
    ])])

    with pytest.raises(QuantityNotConfirmedError, match="requested 2 .* shows 1.0"):
        await ShufersalAdapter().add_to_cart(page, match, 2)


async def test_add_to_cart_treats_absent_product_as_zero_confirmed():
    # the /cart/add response itself can't be trusted (confirmed live: identical HTTP 200
    # for a real and a fake product code) — if the product isn't even found in the
    # follow-up search, that must read as "not actually added", not silently pass.
    match = MatchResult(
        item_code="P1",
        locator={"code": "P1", "name": "Milk", "sellingMethod": {"code": "BY_UNIT"}},
        matched_by="exact_name",
    )
    page = FakePage(search_results=[_ok([])])

    with pytest.raises(QuantityNotConfirmedError, match="shows 0.0"):
        await ShufersalAdapter().add_to_cart(page, match, 1)


async def test_add_to_cart_raises_unsupported_site_flow_when_ajax_call_missing():
    match = MatchResult(
        item_code="P1",
        locator={"code": "P1", "name": "Milk", "sellingMethod": {"code": "BY_UNIT"}},
        matched_by="exact_name",
    )
    page = FakePage(ajax_call_exists=False)

    with pytest.raises(UnsupportedSiteFlowError):
        await ShufersalAdapter().add_to_cart(page, match, 1)
    assert page.add_calls == []  # never attempted the call at all


async def test_add_to_cart_wraps_ajax_call_exception_as_unsupported_site_flow():
    match = MatchResult(
        item_code="P1",
        locator={"code": "P1", "name": "Milk", "sellingMethod": {"code": "BY_UNIT"}},
        matched_by="exact_name",
    )
    page = FakePage(add_raises=RuntimeError("network blew up"))

    with pytest.raises(UnsupportedSiteFlowError, match="network blew up"):
        await ShufersalAdapter().add_to_cart(page, match, 1)


async def test_detect_block_reports_unsupported_site_flow_when_ajax_call_missing():
    page = FakePage(ajax_call_exists=False)

    reason = await ShufersalAdapter().detect_block(page)

    assert reason == "unsupported_site_flow"


async def test_detect_block_returns_none_when_ajax_call_present_and_no_blockers():
    page = FakePage(ajax_call_exists=True)

    reason = await ShufersalAdapter().detect_block(page)

    assert reason is None


async def test_get_cart_url_does_not_use_the_broken_cart_route():
    # /online/he/cart and /online/he/cart/cartsummary were both confirmed live to redirect
    # to a generic fallback page with no cart content — the real cart is a client-side
    # flyout with no dedicated URL, so this must not point at either broken route.
    url = await ShufersalAdapter().get_cart_url(FakePage())

    assert url is not None
    assert not url.rstrip("/").endswith("/cart")
    assert "cartsummary" not in url


# ---------------------------------------------------------------------------
# Recipe-quantity-aware add_to_cart: weight normalization, unit pass-through, the
# whole-package default for a weight/volume unit against a BY_UNIT product, and the
# quantity_conversion_required case when no deterministic conversion exists.
# ---------------------------------------------------------------------------


def _weighed_match():
    return MatchResult(
        item_code="P22",
        locator={"code": "P22", "name": "Tomato", "sellingMethod": {"code": "BY_WEIGHT"}},
        matched_by="exact_name",
    )


def _by_unit_match():
    return MatchResult(
        item_code="P1",
        locator={"code": "P1", "name": "Pasta", "sellingMethod": {"code": "BY_UNIT"}},
        matched_by="exact_name",
    )


async def test_weighed_product_normalizes_grams_to_kg_and_sends_exact_value():
    page = FakePage(search_results=[_ok([
        {"code": "P22", "name": "Tomato", "cartStatus": {"inCart": True, "qty": 0.4}},
    ])])

    result = await ShufersalAdapter().add_to_cart(page, _weighed_match(), 400, "g")

    assert result.quantity == pytest.approx(0.4)
    assert result.unit == "kg"
    assert page.add_calls == [{"productCode": "P22", "sellingMethod": "BY_WEIGHT", "qty": pytest.approx(0.4)}]


async def test_weighed_product_kg_unit_passes_through_unchanged():
    page = FakePage(search_results=[_ok([
        {"code": "P22", "name": "Tomato", "cartStatus": {"inCart": True, "qty": 1.1}},
    ])])

    result = await ShufersalAdapter().add_to_cart(page, _weighed_match(), 1.1, "kg")

    assert result.quantity == pytest.approx(1.1)
    assert result.unit == "kg"


async def test_weighed_product_with_count_unit_raises_quantity_conversion_required():
    # Recipe asked for "2 units" of a product this retailer only sells by weight — no
    # deterministic unit->weight conversion exists, so this must not guess one.
    page = FakePage()

    with pytest.raises(QuantityConversionRequiredError) as exc_info:
        await ShufersalAdapter().add_to_cart(page, _weighed_match(), 2, "unit")

    assert exc_info.value.requested_quantity == 2
    assert exc_info.value.requested_unit == "unit"
    assert exc_info.value.retailer_selling_method == "BY_WEIGHT"
    assert page.add_calls == []  # never attempted a guessed add


async def test_by_unit_product_with_count_unit_uses_recipe_count_directly():
    # "3 eggs" (or here, "3 large") -> quantity 3, not replaced with 1.
    page = FakePage(search_results=[_ok([
        {"code": "P1", "name": "Pasta", "cartStatus": {"inCart": True, "qty": 3}},
    ])])

    result = await ShufersalAdapter().add_to_cart(page, _by_unit_match(), 3, "large")

    assert result.quantity == 3
    assert result.unit == "unit"
    assert page.add_calls == [{"productCode": "P1", "sellingMethod": "BY_UNIT", "qty": 3}]


async def test_by_unit_product_with_weight_unit_buys_one_whole_package():
    # "250 g pasta" matched to a product sold as a whole package -> buy 1 of it, not an
    # invented package count.
    page = FakePage(search_results=[_ok([
        {"code": "P1", "name": "Pasta", "cartStatus": {"inCart": True, "qty": 1}},
    ])])

    result = await ShufersalAdapter().add_to_cart(page, _by_unit_match(), 250, "g")

    assert result.quantity == 1
    assert result.unit == "unit"
    assert page.add_calls == [{"productCode": "P1", "sellingMethod": "BY_UNIT", "qty": 1}]


async def test_by_unit_product_with_weight_unit_buys_enough_whole_packages_when_size_known():
    # "1000 g pasta" matched to a 500 g package -> buy 2, not 1 (a real reported bug).
    page = FakePage(search_results=[_ok([
        {"code": "P1", "name": "Pasta", "cartStatus": {"inCart": True, "qty": 2}},
    ])])

    result = await ShufersalAdapter().add_to_cart(
        page, _by_unit_match(), 1000, "g", package_size=500.0, package_unit="g"
    )

    assert result.quantity == 2
    assert result.unit == "unit"
    assert page.add_calls == [{"productCode": "P1", "sellingMethod": "BY_UNIT", "qty": 2}]


async def test_by_unit_product_with_weight_unit_still_buys_one_when_size_unknown():
    page = FakePage(search_results=[_ok([
        {"code": "P1", "name": "Pasta", "cartStatus": {"inCart": True, "qty": 1}},
    ])])

    result = await ShufersalAdapter().add_to_cart(page, _by_unit_match(), 1000, "g")

    assert result.quantity == 1


async def test_legacy_call_without_unit_is_unchanged():
    page = FakePage(search_results=[_ok([
        {"code": "P1", "name": "Pasta", "cartStatus": {"inCart": True, "qty": 2}},
    ])])

    result = await ShufersalAdapter().add_to_cart(page, _by_unit_match(), 2)

    assert result.quantity == 2
    assert result.unit == "unit"
    assert page.add_calls == [{"productCode": "P1", "sellingMethod": "BY_UNIT", "qty": 2}]
