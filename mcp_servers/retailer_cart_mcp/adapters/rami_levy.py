"""Adapter for rami-levy.co.il. Not exercised by automated tests (those run against
tests/mcp/mock_site_server.py) — this site's structure is not assumed to match
Shufersal's (see shufersal.py) and is implemented independently.

Selectors below were updated during CP9 (2026-08) live verification against the real
site with a captured session. The real front-end search page is `/he/online/search?q=`
(a server-rendered results page) — distinct from `/api/search?q=`, which is a raw JSON
API the front-end calls internally and was what the previous version of this adapter
mistakenly navigated to directly (there is no `.product-box` HTML anywhere on the real
site; that selector never matched anything). Tile identification (`.product-img[alt]`)
and the add-to-cart button/quantity-stepper classes (`button.btn-acc.plus`/`.num-span`)
come from one successfully-rendered results page captured live.

Full add-to-cart could not be re-confirmed end-to-end in the same session: on later
attempts, search-result tiles loaded as empty placeholders (`.product-img` present but
with no `alt` text and no add-to-cart controls rendered at all) — most likely the same
kind of one-time account/delivery setup prerequisite confirmed for Shufersal
(`#assortmentModal`), though no equivalent visible prompt was found for this site to
confirm that specific cause. detect_block() reports this placeholder state as
`assortment_unavailable` rather than guessing further or letting it hang/crash — a
genuine open follow-up, not silently worked around.

No login/checkout/payment method exists here or anywhere in this adapter, by construction.
No bot-evasion, CAPTCHA-bypass, or fingerprint-spoofing is implemented — a detected block is
always reported and the run stops gracefully; it is never worked around.
"""

from urllib.parse import quote

from playwright.async_api import Page

from mcp_servers.retailer_cart_mcp.automation import (
    MatchResult,
    QuantityNotConfirmedError,
    UnsupportedQuantityError,
)

BASE_URL = "https://www.rami-levy.co.il"


class RamiLevyAdapter:
    retailer_name = "rami_levy"

    async def open_site(self, page: Page) -> None:
        await page.goto(BASE_URL)

    async def detect_block(self, page: Page) -> str | None:
        content = await page.content()
        if "recaptcha" in content.lower() or "unusual traffic" in content.lower():
            return "captcha"
        if await page.locator("input#login-email").count() > 0:
            return "login_required"
        # Search-result tiles rendered as empty placeholders (image container present,
        # no product data hydrated into it) — observed live, cause not fully confirmed
        # (see module docstring). Only checked once tiles actually exist, so this never
        # false-positives on pages with no search performed yet (e.g. right after open_site).
        images = page.locator(".product-img")
        if await images.count() > 0 and await page.locator(".product-img[alt]").count() == 0:
            return "assortment_unavailable"
        return None

    async def search_and_match(self, page: Page, item_name: str, item_code: str) -> MatchResult | None:
        # The real site doesn't expose our fixture-style item_code on search tiles (its own
        # barcode is only reachable via the product image's URL), so item_code-based
        # matching isn't attempted here — name matching is the only reliable path.
        await page.goto(f"{BASE_URL}/he/online/search?q={quote(item_name)}")
        images = page.locator(".product-img[alt]")
        count = await images.count()
        if count == 0:
            return None

        for i in range(count):
            img = images.nth(i)
            alt = await img.get_attribute("alt")
            if alt is not None and alt.strip().lower() == item_name.strip().lower():
                tile = img.locator("xpath=ancestor::div[@role='button'][1]")
                return MatchResult(item_code=item_code, locator=tile, matched_by="exact_name")

        first_tile = images.first.locator("xpath=ancestor::div[@role='button'][1]")
        return MatchResult(item_code=item_code, locator=first_tile, matched_by="name_fallback")

    async def add_to_cart(self, page: Page, match: MatchResult, quantity: float) -> float:
        # No direct-fill quantity input on this site — only a stepper (+/- buttons showing
        # a running count), so only whole-unit quantities are representable.
        if quantity != int(quantity):
            raise UnsupportedQuantityError(
                f"Rami Levy only supports whole-unit quantities, got {quantity}"
            )
        quantity = int(quantity)

        await match.locator.hover()
        plus_btn = match.locator.locator("button.btn-acc.plus")
        await plus_btn.wait_for(state="visible", timeout=5000)
        for _ in range(quantity):
            await plus_btn.click()

        qty_display = match.locator.locator(".num-span")
        confirmed = float((await qty_display.inner_text()).strip())
        if confirmed != quantity:
            raise QuantityNotConfirmedError(
                f"requested {quantity} for {match.item_code}, site shows {confirmed}"
            )
        return confirmed

    async def get_cart_url(self, page: Page) -> str | None:
        return f"{BASE_URL}/cart"
