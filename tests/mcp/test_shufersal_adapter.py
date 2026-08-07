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


async def test_search_and_match_falls_back_to_first_result():
    page = FakePage(search_results=[_ok([
        {
            "code": "P2",
            "name": "Something Else",
            "sellingMethod": {"code": "BY_UNIT"},
            "cartStatus": {},
        },
    ])])

    match = await ShufersalAdapter().search_and_match(page, "Milk", "")

    assert match.item_code == "P2"
    assert match.matched_by == "name_fallback"


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

    confirmed = await ShufersalAdapter().add_to_cart(page, match, 2)

    assert confirmed == 2
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
