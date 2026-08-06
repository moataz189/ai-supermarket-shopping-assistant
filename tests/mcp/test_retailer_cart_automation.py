from types import SimpleNamespace

import httpx
import pytest

from mcp_servers.retailer_cart_mcp import automation
from mcp_servers.retailer_cart_mcp.automation import MatchResult, prepare_cart_for_retailer
from tests.mcp.mock_retailer_adapter import MockRetailerAdapter


async def _get_json(url: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()


# ---------------------------------------------------------------------------
# Real mock-site integration tests: exercise the adapter driving a real
# (headless) browser against tests/mcp/mock_site_server.py.
# ---------------------------------------------------------------------------


async def test_quantity_one_is_added_and_confirmed(mock_site):
    items = [{"name": "Milk 3%", "item_code": "SKU-MILK", "quantity": 1}]

    result = await prepare_cart_for_retailer(MockRetailerAdapter(mock_site), items)

    assert result["blocked"] is False
    assert len(result["added"]) == 1
    added = result["added"][0]
    assert added["item_code"] == "SKU-MILK"
    assert added["status"] == "added"
    assert added["matched_by"] == "item_code"
    assert added["quantity_confirmed"] == 1
    assert result["cart_url"] == f"{mock_site}/cart"

    cart = await _get_json(f"{mock_site}/debug/cart")
    assert cart == {"SKU-MILK": 1}


async def test_quantity_greater_than_one_is_set_and_confirmed(mock_site):
    items = [{"name": "Bread", "item_code": "SKU-BREAD", "quantity": 3}]

    result = await prepare_cart_for_retailer(MockRetailerAdapter(mock_site), items)

    assert result["added"][0]["quantity_confirmed"] == 3
    cart = await _get_json(f"{mock_site}/debug/cart")
    assert cart == {"SKU-BREAD": 3}


async def test_item_not_found_continues_with_remaining_items(mock_site):
    items = [
        {"name": "no-such-item", "item_code": "NOPE", "quantity": 1},
        {"name": "Bread", "item_code": "SKU-BREAD", "quantity": 1},
    ]

    result = await prepare_cart_for_retailer(MockRetailerAdapter(mock_site), items)

    assert result["blocked"] is False
    assert result["failed"] == [{"name": "no-such-item", "item_code": "NOPE", "status": "not_found"}]
    assert [a["item_code"] for a in result["added"]] == ["SKU-BREAD"]


async def test_fractional_quantity_explicitly_rejected_for_whole_units_only_product(mock_site):
    items = [{"name": "Eggs (dozen)", "item_code": "SKU-EGGS", "quantity": 1.5}]

    result = await prepare_cart_for_retailer(MockRetailerAdapter(mock_site), items)

    assert result["added"] == []
    assert len(result["failed"]) == 1
    failure = result["failed"][0]
    assert failure["item_code"] == "SKU-EGGS"
    assert failure["status"] == "error"
    assert "whole-unit" in failure["reason"]
    # the site never silently accepted the fractional value
    cart = await _get_json(f"{mock_site}/debug/cart")
    assert cart.get("SKU-EGGS") != 1.5


async def test_quantity_update_failure_is_reported_as_error(mock_site):
    # the mock site silently caps quantity at 10 (simulating a stock/site limit) — the
    # adapter must catch the mismatch between what it asked for and what got confirmed.
    items = [{"name": "Bread", "item_code": "SKU-BREAD", "quantity": 999}]

    result = await prepare_cart_for_retailer(MockRetailerAdapter(mock_site), items)

    assert result["added"] == []
    assert len(result["failed"]) == 1
    failure = result["failed"][0]
    assert failure["status"] == "error"
    assert "999" in failure["reason"]
    assert "10" in failure["reason"]


async def test_duplicate_names_different_item_codes_tracked_independently(mock_site):
    items = [
        {"name": "Yogurt", "item_code": "SKU-YOG-A", "quantity": 1},
        {"name": "Yogurt", "item_code": "SKU-YOG-B", "quantity": 2},
    ]

    result = await prepare_cart_for_retailer(MockRetailerAdapter(mock_site), items)

    added_by_code = {a["item_code"]: a["quantity_confirmed"] for a in result["added"]}
    assert added_by_code == {"SKU-YOG-A": 1, "SKU-YOG-B": 2}
    cart = await _get_json(f"{mock_site}/debug/cart")
    assert cart == {"SKU-YOG-A": 1, "SKU-YOG-B": 2}


async def test_matched_by_exact_name_fallback_when_item_code_unknown(mock_site):
    items = [{"name": "Bread", "item_code": "UNKNOWN-CODE", "quantity": 1}]

    result = await prepare_cart_for_retailer(MockRetailerAdapter(mock_site), items)

    assert result["added"][0]["matched_by"] == "exact_name"
    assert result["added"][0]["item_code"] == "UNKNOWN-CODE"  # echoes the request


async def test_matched_by_name_fallback_when_no_exact_match(mock_site):
    items = [{"name": "Milk", "item_code": "UNKNOWN-CODE-2", "quantity": 1}]

    result = await prepare_cart_for_retailer(MockRetailerAdapter(mock_site), items)

    assert result["added"][0]["matched_by"] == "name_fallback"


async def test_captcha_stops_gracefully_and_preserves_added_items(mock_site):
    items = [
        {"name": "Bread", "item_code": "SKU-BREAD", "quantity": 1},
        {"name": "TRIGGER_CAPTCHA", "item_code": "X1", "quantity": 1},
        {"name": "Milk 3%", "item_code": "SKU-MILK", "quantity": 1},
    ]

    result = await prepare_cart_for_retailer(MockRetailerAdapter(mock_site), items)

    assert result["blocked"] is True
    assert result["blocked_reason"] == "captcha"
    assert result["cart_url"] is None
    assert [a["item_code"] for a in result["added"]] == ["SKU-BREAD"]
    failed_by_code = {f["item_code"]: f["reason"] for f in result["failed"]}
    assert failed_by_code == {"X1": "skipped_after_block", "SKU-MILK": "skipped_after_block"}


async def test_login_wall_stops_gracefully(mock_site):
    items = [{"name": "TRIGGER_LOGIN", "item_code": "X2", "quantity": 1}]

    result = await prepare_cart_for_retailer(MockRetailerAdapter(mock_site), items)

    assert result["blocked"] is True
    assert result["blocked_reason"] == "login_required"
    assert result["added"] == []
    assert result["failed"] == [{"name": "TRIGGER_LOGIN", "item_code": "X2", "status": "error", "reason": "skipped_after_block"}]


async def test_successful_run_never_visits_checkout(mock_site):
    items = [{"name": "Bread", "item_code": "SKU-BREAD", "quantity": 2}]

    await prepare_cart_for_retailer(MockRetailerAdapter(mock_site), items)

    visits = await _get_json(f"{mock_site}/debug/checkout-visits")
    assert visits["count"] == 0


async def test_blocked_run_never_visits_checkout(mock_site):
    items = [{"name": "TRIGGER_CAPTCHA", "item_code": "X1", "quantity": 1}]

    await prepare_cart_for_retailer(MockRetailerAdapter(mock_site), items)

    visits = await _get_json(f"{mock_site}/debug/checkout-visits")
    assert visits["count"] == 0


# ---------------------------------------------------------------------------
# Orchestration-level tests: a scripted in-memory fake adapter (no real HTML)
# pins down exact browser-cleanup and block-checkpoint behavior that would be
# awkward to provoke through the mock site's HTML.
# ---------------------------------------------------------------------------


class _FakePage:
    pass


class _FakeContext:
    async def new_page(self):
        return _FakePage()

    async def close(self):
        pass


class _FakeBrowser:
    def __init__(self):
        self.closed = False

    async def new_context(self, storage_state=None):
        return _FakeContext()

    async def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, browser):
        self._browser = browser

    async def launch(self, headless=True):
        return self._browser


class _FakePlaywrightCM:
    def __init__(self, browser):
        self._browser = browser

    async def __aenter__(self):
        return SimpleNamespace(chromium=_FakeChromium(self._browser))

    async def __aexit__(self, *exc_info):
        return False


def _patch_playwright(monkeypatch, browser):
    monkeypatch.setattr(automation, "async_playwright", lambda: _FakePlaywrightCM(browser))


class _ScriptedAdapter:
    retailer_name = "fake"

    def __init__(self, *, fail_at=None):
        self.fail_at = fail_at

    async def open_site(self, page):
        if self.fail_at == "open_site":
            raise RuntimeError("open_site boom")

    async def detect_block(self, page):
        if self.fail_at == "detect_block":
            raise RuntimeError("detect_block boom")

    async def search_and_match(self, page, item_name, item_code):
        if self.fail_at == "search_and_match":
            raise RuntimeError("search_and_match boom")
        return MatchResult(item_code=item_code, locator=None, matched_by="item_code")

    async def add_to_cart(self, page, match, quantity):
        if self.fail_at == "add_to_cart":
            raise RuntimeError("add_to_cart boom")
        return quantity

    async def get_cart_url(self, page):
        if self.fail_at == "get_cart_url":
            raise RuntimeError("get_cart_url boom")
        return "http://example.test/cart"


@pytest.mark.parametrize(
    "fail_at", ["open_site", "detect_block", "search_and_match", "add_to_cart", "get_cart_url"]
)
async def test_browser_always_closes_on_failure(monkeypatch, fail_at):
    browser = _FakeBrowser()
    _patch_playwright(monkeypatch, browser)
    adapter = _ScriptedAdapter(fail_at=fail_at)

    result = await prepare_cart_for_retailer(adapter, [{"name": "x", "item_code": "c1", "quantity": 1}])

    assert browser.closed is True
    assert isinstance(result, dict)


async def test_get_cart_url_failure_does_not_block_or_lose_added_items(monkeypatch):
    browser = _FakeBrowser()
    _patch_playwright(monkeypatch, browser)
    adapter = _ScriptedAdapter(fail_at="get_cart_url")

    result = await prepare_cart_for_retailer(adapter, [{"name": "x", "item_code": "c1", "quantity": 1}])

    assert browser.closed is True
    assert result["blocked"] is False
    assert result["cart_url"] is None
    assert result["added"] == [
        {"name": "x", "item_code": "c1", "status": "added", "matched_by": "item_code", "quantity_confirmed": 1}
    ]


async def test_detect_block_called_at_each_checkpoint(monkeypatch):
    browser = _FakeBrowser()
    _patch_playwright(monkeypatch, browser)

    class CountingAdapter(_ScriptedAdapter):
        def __init__(self):
            super().__init__()
            self.detect_block_calls = 0

        async def detect_block(self, page):
            self.detect_block_calls += 1

    adapter = CountingAdapter()
    items = [{"name": "a", "item_code": "c1", "quantity": 1}, {"name": "b", "item_code": "c2", "quantity": 1}]

    await prepare_cart_for_retailer(adapter, items)

    # 1 (after open) + 2 items * 2 (after search, after add) + 1 (before cart_url) = 6
    assert adapter.detect_block_calls == 6


async def test_block_detected_right_after_add_preserves_that_item(monkeypatch):
    browser = _FakeBrowser()
    _patch_playwright(monkeypatch, browser)

    class BlockAfterAddAdapter(_ScriptedAdapter):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def detect_block(self, page):
            self.calls += 1
            # 1st call: after open_site. 2nd: after search for item c1. 3rd: after add
            # for item c1 -> blocked from here on.
            return "captcha" if self.calls >= 3 else None

    adapter = BlockAfterAddAdapter()
    items = [
        {"name": "a", "item_code": "c1", "quantity": 1},
        {"name": "b", "item_code": "c2", "quantity": 1},
    ]

    result = await prepare_cart_for_retailer(adapter, items)

    assert result["blocked"] is True
    assert result["blocked_reason"] == "captcha"
    assert [a["item_code"] for a in result["added"]] == ["c1"]
    assert {f["item_code"]: f["reason"] for f in result["failed"]} == {"c2": "skipped_after_block"}
    assert result["cart_url"] is None


async def test_skipped_after_block_tracks_by_item_code_not_name(monkeypatch):
    browser = _FakeBrowser()
    _patch_playwright(monkeypatch, browser)

    class BlockImmediatelyAdapter(_ScriptedAdapter):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def detect_block(self, page):
            self.calls += 1
            return "captcha" if self.calls >= 1 else None

    adapter = BlockImmediatelyAdapter()
    items = [
        {"name": "Yogurt", "item_code": "SKU-YOG-A", "quantity": 1},
        {"name": "Yogurt", "item_code": "SKU-YOG-B", "quantity": 1},
    ]

    result = await prepare_cart_for_retailer(adapter, items)

    failed_by_code = {f["item_code"]: f["reason"] for f in result["failed"]}
    assert failed_by_code == {"SKU-YOG-A": "skipped_after_block", "SKU-YOG-B": "skipped_after_block"}
