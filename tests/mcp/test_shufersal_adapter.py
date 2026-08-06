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
            if not self._search_results:
                raise AssertionError("no more scripted search responses")
            return self._search_results.pop(0)
        raise AssertionError(f"unexpected script: {script}")


def _ok(results):
    return {"ok": True, "results": results}


async def test_search_and_match_exact_name_match():
    page = FakePage(search_results=[_ok([
        {"code": "P1", "name": "Milk", "sellingMethod": {"code": "BY_UNIT"}, "cartStatus": {}},
    ])])

    match = await ShufersalAdapter().search_and_match(page, "Milk", "ignored-code")

    assert match.item_code == "P1"
    assert match.matched_by == "exact_name"


async def test_search_and_match_case_insensitive_exact_match():
    page = FakePage(search_results=[_ok([
        {"code": "P1", "name": "MILK 3%", "sellingMethod": {"code": "BY_UNIT"}, "cartStatus": {}},
    ])])

    match = await ShufersalAdapter().search_and_match(page, "milk 3%", "ignored-code")

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

    match = await ShufersalAdapter().search_and_match(page, "Milk", "ignored-code")

    assert match.item_code == "P2"
    assert match.matched_by == "name_fallback"


async def test_search_and_match_returns_none_when_no_results():
    page = FakePage(search_results=[_ok([])])

    match = await ShufersalAdapter().search_and_match(page, "Milk", "ignored-code")

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
