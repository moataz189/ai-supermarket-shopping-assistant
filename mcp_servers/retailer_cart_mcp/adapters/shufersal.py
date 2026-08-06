"""Adapter for shufersal.co.il. Not exercised by automated tests (those run against
tests/mcp/mock_site_server.py). Selectors below were verified live during CP9 (2026-08)
against the real site with a captured session — real search URL, real tile attributes
(`data-product-code`/`data-product-name`, not the earlier `data-testid` guesses which
don't exist on the real site), real add-to-cart button/quantity-input classes. Re-verify
periodically; real-site structure still drifts over time.

Two real, deterministic bugs were found and fixed live during this verification, both with
passing regression tests:
1. The quantity-confirmation step used to fill the quantity `<input>` and then read that
   *same* input back — tautological, since it can only ever report what this method itself
   just wrote. Now reloads the page and re-queries by the matched item_code before reading
   back the quantity, a genuine server round-trip instead of a self-check.
2. `search_and_match` used to search by item_code first, then by name — two navigations in
   the same browser context. Found live: a *second* full navigation in the same context
   leaves the add-to-cart button permanently hidden on this site (reproduced 10+ ways;
   confirmed stuck even after 20+ seconds of active polling, not a brief loading delay).
   Fixed two ways together: `automation.py` now gives each item its own fresh browser
   context, and this adapter searches by name only (the item_code search was always a
   wasted navigation anyway — our fixture-style codes never match the site's own
   "P_xxxxx" internal codes).

**What's still unresolved, honestly:** even after both fixes, add-to-cart has been
observed to intermittently get stuck at a *later* click (`button.js-update-cart`,
immediately after the first click already succeeded) — including on a request that had
fully succeeded moments earlier with identical code. That points to genuine timing/session
variance on Shufersal's side (most plausibly its personalization/analytics scripts,
network conditions, or A/B experiment assignment), not a deterministic client-side bug —
investigated but not fully root-caused. Both clicks in `add_to_cart` use a shortened
timeout so a stuck click fails in ~10s rather than tying up the whole request for the
default ~30s per click; this does not fix the flakiness, it just fails faster and cheaper
when it happens. Do not read "selectors verified" above as "add-to-cart is 100% reliable."

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
        # Only ever searches by name — no by-code pre-search. Two reasons: our
        # fixture-style item_code never matches the real site's own "P_xxxxx" internal
        # codes anyway (so it was always a wasted navigation in practice), and, found live
        # during CP9 verification, a *second* full navigation within the same browser
        # context leaves the add-to-cart button permanently hidden on this site (reproduced
        # 10+ ways; not a timing issue — confirmed stuck past 20s of active polling).
        # Combined with automation.py giving each item its own fresh context, this keeps
        # every item's search down to the one navigation that context will ever make.
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
        #
        # Both clicks below use a shorter-than-default timeout (Playwright's default is
        # 30s). This site's add/update buttons have been observed, live, to get stuck in a
        # not-visible state that never resolves even after 20+ seconds of active polling —
        # not a brief loading delay a longer wait would fix, so there's nothing to gain
        # from waiting the full default; failing in ~10s instead of ~40s lets a stuck
        # add-to-cart surface as a clear per-item failure faster, without pretending a
        # shorter timeout makes the underlying flakiness go away.
        click_timeout_ms = 10_000
        container = match.locator.locator(".addToCartWrapperOld")
        await container.locator("button.js-add-to-cart").click(timeout=click_timeout_ms)

        qty_input = container.locator("input.js-qty-selector-input")
        await qty_input.fill(str(quantity))
        await container.locator("button.js-update-cart").click(timeout=click_timeout_ms)
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
