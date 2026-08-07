"""Adapter for rami-levy.co.il. Not exercised by automated tests (those run against
tests/mcp/mock_site_server.py) — this site's structure is not assumed to match
Shufersal's (see shufersal.py) and is implemented independently.

Selectors below were updated during CP9 (2026-08) live verification against the real
site with a captured session. The real front-end search page is `/he/online/search?q=`
(a server-rendered results page) — distinct from `/api/search?q=`, which is a raw JSON
API the front-end calls internally and was what the previous version of this adapter
mistakenly navigated to directly (there is no `.product-box` HTML anywhere on the real
site; that selector never matched anything).

A CP9 follow-up (2026-08-08, live) root-caused what earlier looked like a site block
(`assortment_unavailable` on every real search) to two wrong selectors in this adapter,
not an actual block:
- `.product-img` is a `<div>` wrapper; the real `alt` text lives on the `<img>` nested
  inside it. `.product-img[alt]` can therefore never match anything — confirmed live
  (`.product-img[alt]` count 0 on a results page that was, on inspection, fully
  hydrated with real product tiles, prices and images). Fixed to `.product-img img[alt]`.
- The tile container is not reachable via `ancestor::div[@role='button']` — there is a
  `role="button"` element in each tile, but it's a *sibling* of the image wrapper, not
  an ancestor (confirmed live via `closest('[role=button]')` returning null from the
  image). The actual card container is the closest ancestor carrying the
  `big-plus-minus` class (also confirmed live to be exactly one match per tile), which
  is what the `button.btn-acc.plus`/`.num-span` add-to-cart controls render inside of
  once hovered.

A full add/confirm round trip was re-verified live end-to-end with the corrected
selectors (hover -> click `button.btn-acc.plus` -> `.num-span` read back as `"1"`).

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
        # no product data hydrated into it) — a genuine site-side state, distinct from
        # the normal case where `.product-img` divs are present but their `alt` text
        # lives on the nested `<img>` (see module docstring), which is why this checks
        # `.product-img img[alt]`, not `.product-img[alt]`. Only checked once tiles
        # actually exist, so this never false-positives on pages with no search
        # performed yet (e.g. right after open_site).
        images = page.locator(".product-img")
        if await images.count() > 0 and await page.locator(".product-img img[alt]").count() == 0:
            return "assortment_unavailable"
        return None

    async def search_and_match(self, page: Page, item_name: str, item_code: str) -> MatchResult | None:
        # The real site doesn't expose our fixture-style item_code on search tiles (its own
        # barcode is only reachable via the product image's URL), so item_code-based
        # matching isn't attempted here — name matching is the only reliable path.
        await page.goto(f"{BASE_URL}/he/online/search?q={quote(item_name)}")
        # `alt` lives on the `<img>` nested inside `.product-img`, not on that div itself
        # (see module docstring). The tile/card container — where the add-to-cart
        # controls render — is the closest ancestor carrying `big-plus-minus`; there is
        # no `role="button"` ancestor of the image (that role is on an unrelated sibling
        # element within the same tile).
        images = page.locator(".product-img img[alt]")
        count = await images.count()
        if count == 0:
            return None

        for i in range(count):
            img = images.nth(i)
            alt = await img.get_attribute("alt")
            if alt is not None and alt.strip().lower() == item_name.strip().lower():
                tile = img.locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' big-plus-minus ')][1]")
                return MatchResult(item_code=item_code, locator=tile, matched_by="exact_name")

        first_tile = images.first.locator(
            "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' big-plus-minus ')][1]"
        )
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
