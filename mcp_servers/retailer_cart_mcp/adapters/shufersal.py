"""Adapter for shufersal.co.il. Not exercised by automated tests (those run against
tests/mcp/mock_site_server.py); tests/mcp/test_shufersal_adapter.py unit-tests this
adapter's logic against a fake `page.evaluate`. Re-verify periodically — real-site
behavior drifts over time and this adapter leans on internal site interfaces (see below).

**This adapter drives the site through its own internal JavaScript/fetch flow, not DOM
clicks.** That flow is undocumented and not a public API — it was reverse-engineered by
inspecting the live site during CP9 (2026-08) with a captured, already-authenticated
session, and may change without notice:
- Search: `GET {BASE_URL}/online/he/search/results?q=...&limit=...` (same-origin `fetch`,
  `credentials: 'include'`) — returns JSON `{results: [{code, name, sellingMethod: {code},
  cartStatus: {inCart, qty, ...}, ...}]}`.
- Add-to-cart: the page's own `window.ajaxCall(url, jsonBody, callback, contentType,
  cartContext)` helper, called from inside `page.evaluate()` so it runs with the page's
  existing authenticated session/cookies — no separate login or session handling here.

Both were confirmed live against a real account before this adapter was written this way:
the search schema and the add-to-cart payload shape were captured directly from the page's
own JS source and network traffic; a real add was confirmed to persist server-side (checked
both via a fresh follow-up search call and independently via a full page reload); no
checkout, payment, login automation, CAPTCHA bypass, or anti-bot evasion was added or is
needed for any of this.

**`/cart/add`'s response body is not a trustworthy success signal — confirmed live.** It
returns HTTP 200 with an all-but-identical generic mini-cart HTML fragment for a real
product code *and* for a completely fake one; there is no `success: false` or error status
to check. So this adapter never trusts that response. After calling `window.ajaxCall`, it
independently re-queries the search endpoint (a fresh network round trip, not a cached
value) and reads the authoritative `cartStatus.qty` for the matched product code back from
the server. Only that counts as confirmation; a mismatch raises QuantityNotConfirmedError
exactly like a site-side cap or stock limit would.

If `window.ajaxCall` isn't a function on the loaded page (the site changed its internal
JS), `detect_block` reports `unsupported_site_flow` immediately so the run stops cleanly
instead of proceeding on a broken assumption; the same failure raised mid-flow (a search or
add call throwing) surfaces as a structured per-item error with `unsupported_site_flow` in
the reason. There is no fallback to DOM automation — an internal interface disappearing is
treated as a hard, reported stop, not silently worked around.

No login/checkout/payment method exists here or anywhere in this adapter, by construction.
No bot-evasion, CAPTCHA-bypass, or fingerprint-spoofing is implemented — a detected block is
always reported and the run stops gracefully; it is never worked around.
"""

from urllib.parse import quote

from playwright.async_api import Page

from mcp_servers.retailer_cart_mcp.automation import (
    MatchResult,
    QuantityNotConfirmedError,
    UnsupportedSiteFlowError,
)

BASE_URL = "https://www.shufersal.co.il"


class ShufersalAdapter:
    retailer_name = "shufersal"

    async def open_site(self, page: Page) -> None:
        await page.goto(BASE_URL)

    async def detect_block(self, page: Page) -> str | None:
        content = await page.content()
        if "px-captcha" in content or "are you human" in content.lower():
            return "captcha"
        if await page.locator("#login-password").count() > 0:
            return "login_required"
        if await page.locator("#assortmentModal.in").count() > 0:
            return "delivery_address_required"
        has_ajax_call = await page.evaluate("() => typeof window.ajaxCall === 'function'")
        if not has_ajax_call:
            return "unsupported_site_flow"
        return None

    async def _search(self, page: Page, query: str, limit: int = 20) -> list[dict]:
        url = f"{BASE_URL}/online/he/search/results?q={quote(query)}&limit={limit}"
        try:
            response = await page.evaluate(
                """
                async (url) => {
                    const res = await fetch(url, {
                        headers: {'accept': 'application/json', 'x-requested-with': 'XMLHttpRequest'},
                        credentials: 'include'
                    });
                    if (!res.ok) {
                        return {ok: false, status: res.status};
                    }
                    const body = await res.json();
                    return {ok: true, results: body.results || []};
                }
                """,
                url,
            )
        except Exception as exc:
            raise UnsupportedSiteFlowError(f"search endpoint call failed: {exc}") from exc

        if not response.get("ok"):
            raise UnsupportedSiteFlowError(f"search endpoint returned status {response.get('status')}")
        return response["results"]

    async def search_and_match(self, page: Page, item_name: str, item_code: str) -> MatchResult | None:
        # Only ever searches by name — our fixture-style item_code never matches the real
        # site's own "P_xxxxx" internal codes, so a by-code pre-search was always wasted.
        # One navigation per fresh context (automation.py gives each item its own), then
        # the rest of this adapter talks to the site entirely through same-origin fetch
        # calls from inside page.evaluate() — no further navigation is needed at all.
        await page.goto(BASE_URL)
        results = await self._search(page, item_name)
        if not results:
            return None

        for item in results:
            name = item.get("name")
            if name is not None and name.strip().lower() == item_name.strip().lower():
                return MatchResult(item_code=item["code"], locator=item, matched_by="exact_name")

        first = results[0]
        return MatchResult(item_code=first["code"], locator=first, matched_by="name_fallback")

    async def _confirm_quantity(self, page: Page, item_name: str, item_code: str) -> float:
        # A fresh server round trip, not a locally-held value — re-runs the same search
        # this adapter already trusts for matching, and reads back the authoritative
        # cartStatus for the specific product code just added.
        results = await self._search(page, item_name)
        for item in results:
            if item.get("code") == item_code:
                cart_status = item.get("cartStatus") or {}
                qty = cart_status.get("qty")
                return float(qty) if qty is not None else 0.0
        return 0.0

    async def add_to_cart(self, page: Page, match: MatchResult, quantity: float) -> float:
        item = match.locator
        selling_method = (item.get("sellingMethod") or {}).get("code", "BY_UNIT")

        has_ajax_call = await page.evaluate("() => typeof window.ajaxCall === 'function'")
        if not has_ajax_call:
            raise UnsupportedSiteFlowError("window.ajaxCall is not available on this page")

        try:
            await page.evaluate(
                """
                async ({productCode, sellingMethod, qty}) => {
                    await window.ajaxCall('/cart/add', JSON.stringify({
                        productCodePost: productCode,
                        productCode: productCode,
                        sellingMethod: sellingMethod,
                        qty: qty,
                        frontQuantity: qty,
                        comment: '',
                        affiliateCode: ''
                    }), () => {}, null, {openFrom: 'SEARCH', recommendationType: 'AUTOCOMPLETE_LIST'});
                }
                """,
                {"productCode": match.item_code, "sellingMethod": selling_method, "qty": quantity},
            )
        except Exception as exc:
            raise UnsupportedSiteFlowError(f"/cart/add call failed: {exc}") from exc

        confirmed = await self._confirm_quantity(page, item.get("name", ""), match.item_code)
        if confirmed != quantity:
            raise QuantityNotConfirmedError(
                f"requested {quantity} for {match.item_code}, site cart shows {confirmed}"
            )
        return confirmed

    async def get_cart_url(self, page: Page) -> str | None:
        return f"{BASE_URL}/online/he/cart"
