"""Adapter for shufersal.co.il. Not exercised by automated tests (those run against
tests/mcp/mock_site_server.py). Selectors below were verified live during CP9 (2026-08)
against the real site with a captured session — real search URL, real tile attributes
(`data-product-code`/`data-product-name`, not the earlier `data-testid` guesses which
don't exist on the real site), real add-to-cart button/quantity-input classes. Re-verify
periodically; real-site structure still drifts over time.

Full add-to-cart confirmed working end-to-end live, cross-checked against an independent
fresh page reload (not just this adapter's own report) showing the real cart's item count
and total actually increase by the added item's real price. The quantity-confirmation step
deliberately reloads the page and re-queries by the matched item_code before reading back
the quantity — reading the same `<input>` this method itself just filled would only prove
the DOM write succeeded, not that the site's backend actually persisted it (an earlier
version of this method had exactly that bug: it filled the input then read that same input
back, so it reported `confirmed` even on requests that never actually reached the server).

On an account with no delivery method/address configured yet, clicking "add" instead opens
a mandatory "how would you like to receive your order?" modal (`#assortmentModal`) that
blocks the add — confirmed live, screenshot captured. Configuring a delivery address is
one-time account setup, not a per-request cart action, so it's intentionally out of scope
for this automation (same reasoning as login — see login.py); detect_block() reports it as
`delivery_address_required` instead of silently failing or hanging.

No login/checkout/payment method exists here or anywhere in this adapter, by construction.
No bot-evasion, CAPTCHA-bypass, or fingerprint-spoofing is implemented — a detected block is
always reported and the run stops gracefully; it is never worked around.
"""

from urllib.parse import quote

from playwright.async_api import Page

from mcp_servers.retailer_cart_mcp.automation import MatchResult, QuantityNotConfirmedError

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
        return None

    async def search_and_match(self, page: Page, item_name: str, item_code: str) -> MatchResult | None:
        await page.goto(f"{BASE_URL}/online/he/search?text={quote(item_code)}")
        by_code = page.locator(f"li.tileBlock[data-product-code='{item_code}']")
        if await by_code.count() > 0:
            return MatchResult(item_code=item_code, locator=by_code.first, matched_by="item_code")

        await page.goto(f"{BASE_URL}/online/he/search?text={quote(item_name)}")
        tiles = page.locator("li.tileBlock[data-product-code]")
        count = await tiles.count()
        if count == 0:
            return None

        for i in range(count):
            tile = tiles.nth(i)
            name = await tile.get_attribute("data-product-name")
            if name is not None and name.strip().lower() == item_name.strip().lower():
                code = await tile.get_attribute("data-product-code")
                return MatchResult(item_code=code, locator=tile, matched_by="exact_name")

        first = tiles.first
        code = await first.get_attribute("data-product-code")
        return MatchResult(item_code=code, locator=first, matched_by="name_fallback")

    async def add_to_cart(self, page: Page, match: MatchResult, quantity: float) -> float:
        # Desktop cart controls only (`.addToCartWrapperOld`) — the real page also renders a
        # parallel mobile-only copy of the same controls (`.addToCartMobileWrapperNew`,
        # hidden at desktop viewport widths via `hidden-sm hidden-md hidden-lg`), which would
        # be a second, ambiguous match for the same selectors without this scope.
        container = match.locator.locator(".addToCartWrapperOld")
        await container.locator("button.js-add-to-cart").click()

        qty_input = container.locator("input.js-qty-selector-input")
        await qty_input.fill(str(quantity))
        await container.locator("button.js-update-cart").click()
        await page.wait_for_timeout(1000)

        # Confirm against a fresh page reload, re-querying by the matched item_code (not
        # the original tile-index locator, whose position could shift on reload) — reading
        # back the same input we just filled would only prove the DOM write succeeded, not
        # that the site's backend actually persisted the add.
        await page.reload()
        fresh_tile = page.locator(f"li.tileBlock[data-product-code='{match.item_code}']").first
        fresh_qty_input = fresh_tile.locator(".addToCartWrapperOld input.js-qty-selector-input")
        confirmed_attr = await fresh_qty_input.input_value()
        confirmed = float(confirmed_attr)
        if confirmed != quantity:
            raise QuantityNotConfirmedError(
                f"requested {quantity} for {match.item_code}, site shows {confirmed}"
            )
        return confirmed

    async def get_cart_url(self, page: Page) -> str | None:
        return f"{BASE_URL}/online/he/cart"
