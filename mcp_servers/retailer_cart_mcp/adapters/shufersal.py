"""Best-effort adapter for shufersal.co.il. Not exercised by automated tests (those run
against tests/mcp/mock_site_server.py) — verify selectors manually against the live site
periodically; real-site structure drifts and these are unverified guesses. detect_block()
is the safety net for CAPTCHA/bot-detection and selector/structure drift: if selectors stop
matching, search_and_match naturally returns None (item reported not_found) rather than
mis-clicking, and detect_block gets a chance to catch an actual bot wall.

No login/checkout/payment method exists here or anywhere in this adapter, by construction.
No bot-evasion, CAPTCHA-bypass, or fingerprint-spoofing is implemented — a detected block is
always reported and the run stops gracefully; it is never worked around.
"""

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
        return None

    async def search_and_match(self, page: Page, item_name: str, item_code: str) -> MatchResult | None:
        await page.goto(f"{BASE_URL}/online/he/search?text={item_code}")
        by_code = page.locator(f"[data-testid='product-tile'][data-item-code='{item_code}']")
        if await by_code.count() > 0:
            return MatchResult(item_code=item_code, locator=by_code.first, matched_by="item_code")

        await page.goto(f"{BASE_URL}/online/he/search?text={item_name}")
        tiles = page.locator("[data-testid='product-tile']")
        count = await tiles.count()
        if count == 0:
            return None

        for i in range(count):
            tile = tiles.nth(i)
            name = await tile.get_attribute("data-product-name")
            if name is not None and name.strip().lower() == item_name.strip().lower():
                code = await tile.get_attribute("data-item-code")
                return MatchResult(item_code=code, locator=tile, matched_by="exact_name")

        first = tiles.first
        code = await first.get_attribute("data-item-code")
        return MatchResult(item_code=code, locator=first, matched_by="name_fallback")

    async def add_to_cart(self, page: Page, match: MatchResult, quantity: float) -> float:
        await match.locator.locator("button[data-testid='add-to-cart']").click()

        qty_input = page.locator("[data-testid='cart-quantity-input']")
        await qty_input.fill(str(quantity))
        await page.locator("[data-testid='cart-quantity-update']").click()

        confirmed_attr = await page.locator("[data-testid='cart-quantity-input']").input_value()
        confirmed = float(confirmed_attr)
        if confirmed != quantity:
            raise QuantityNotConfirmedError(
                f"requested {quantity} for {match.item_code}, site shows {confirmed}"
            )
        return confirmed

    async def get_cart_url(self, page: Page) -> str | None:
        return f"{BASE_URL}/online/he/cart"
