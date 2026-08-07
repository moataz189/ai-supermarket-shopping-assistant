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

A real multi-item run against this fixed adapter (2026-08-08) still intermittently
reported `assortment_unavailable` on later items in the same run, even though a manual
re-check of the identical search immediately after showed a fully hydrated page. Not
reproducible locally even under concurrent load, but the difference is resource
headroom: `page.goto()` only waits for the `load` event, not for this Vue app to finish
hydrating product data into the SSR tile shells, and the container this actually runs in
has much less CPU/memory slack than a dev machine to finish that hydration within the
same wall-clock window. `_wait_for_tiles_hydrated()` below waits (up to 8s, on the same
already-loaded page — no retry, no new request, nothing that looks like evasion) for
`.product-img img[alt]` to catch up to `.product-img` before either adapter method reads
tile state, so a slow-but-genuine render no longer reads as a false block.

A further real run (2026-08-08) surfaced two more per-item outcomes:
- Loose/weighed produce (tomatoes, tile marked "לק"ג") reported `QuantityNotConfirmedError`
  ("requested 1 ... site shows 0.5") — confirmed live that each "+" click adds the site's
  own fixed weight step (0.5), not a whole "1". A second click initially appeared not to
  register at all; re-investigated live and root-caused to a one-time "delivery area"
  modal (`#delivery-modal`) that a session's very first add-to-cart click triggers,
  blocking all further interaction until dismissed via its `#close-popup` button — not a
  per-click behavior (confirmed live: closing it once, every click after that increments
  cleanly, 5 straight clicks went 0.5 -> 1 -> 1.5 -> 2 -> 2.5 with no plateau). Per
  explicit product decision, `add_to_cart` detects the `span[aria-label="לקילו גרם"]`
  marker and routes to `_add_weighed_item`, which clicks (dismissing that one-time modal
  if it appears) until the requested quantity is reached, reporting whatever multiple of
  the site's step got there as a successful add — never an error, since there's no way to
  hit an arbitrary exact weight on this control regardless. If a click ever doesn't move
  the confirmed number (a genuine site-side cap, e.g. stock or a promo limit, rather than
  the one-time modal), it stops there and reports that lower amount as the successful add
  instead of looping or failing. This is deliberately generic (the marker, not a
  name/category allowlist), so it applies to any weight-sold product, not just tomatoes.
- A packaged bread item reported `QuantityNotConfirmedError` ("requested 1 ... site shows
  2.0") on one run but not on repeated live re-checks of the same product/click sequence
  immediately after (which consistently confirmed "1"). Left as-is: the whole-unit path
  still never silently accepts a site-confirmed quantity that doesn't match what was
  requested, so a stale promo/pack-size default or a one-off UI quirk surfaces as an
  honest, reported mismatch rather than a silent wrong add — unlike the weighed-produce
  case above, there's no known, generic site-side reason a whole-unit item wouldn't
  confirm the exact requested count.

No login/checkout/payment method exists here or anywhere in this adapter, by construction.
No bot-evasion, CAPTCHA-bypass, or fingerprint-spoofing is implemented — a detected block is
always reported and the run stops gracefully; it is never worked around.
"""

from urllib.parse import quote

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from mcp_servers.retailer_cart_mcp.automation import (
    MatchResult,
    QuantityNotConfirmedError,
    UnsupportedQuantityError,
)

BASE_URL = "https://www.rami-levy.co.il"


async def _wait_for_tiles_hydrated(page: Page, timeout_ms: int = 8000) -> None:
    """Waits for search-result tiles' `alt` text to hydrate in, if any tiles are present
    at all. Best-effort: on timeout this just falls through, and the caller's own
    count()-based check makes the final (honest) call using whatever state exists then."""
    try:
        await page.wait_for_function(
            """() => {
                const wraps = document.querySelectorAll('.product-img');
                if (wraps.length === 0) return true;
                return document.querySelectorAll('.product-img img[alt]').length === wraps.length;
            }""",
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        pass  # fall through — caller's own count()-based check makes the final call


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
        await _wait_for_tiles_hydrated(page)
        images = page.locator(".product-img")
        if await images.count() > 0 and await page.locator(".product-img img[alt]").count() == 0:
            return "assortment_unavailable"
        return None

    async def search_and_match(self, page: Page, item_name: str, item_code: str) -> MatchResult | None:
        # The real site doesn't expose our fixture-style item_code on search tiles (its own
        # barcode is only reachable via the product image's URL), so item_code-based
        # matching isn't attempted here — name matching is the only reliable path.
        await page.goto(f"{BASE_URL}/he/online/search?q={quote(item_name)}")
        await _wait_for_tiles_hydrated(page)
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
        # Loose/weighed produce (marked "לק"ג" — "per kg" — on the tile, confirmed live,
        # CP9 2026-08-08) doesn't behave like a normal whole-unit stepper: each click adds
        # the site's own fixed weight step (observed: 0.5) rather than a whole "1" — so
        # this clicks repeatedly until the requested quantity is reached, landing on
        # whatever multiple of that step gets there (see _add_weighed_item).
        if await match.locator.locator('span[aria-label="לקילו גרם"]').count() > 0:
            return await self._add_weighed_item(page, match, quantity)

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

    async def _add_weighed_item(self, page: Page, match: MatchResult, quantity: float) -> float:
        # A product's *very first* add-to-cart click in a fresh session triggers a
        # one-time "delivery area" modal (#delivery-modal) that blocks all further page
        # interaction until dismissed via its #close-popup button — confirmed live,
        # CP9 2026-08-08, that this is a one-off per-session gate, not a per-click
        # behavior: every click after the first one closes cleanly with no modal, and a
        # sequence of 5 clicks on the same tile increased 0.5 -> 1 -> 1.5 -> 2 -> 2.5
        # with no plateau. If a click ever DOESN'T change the confirmed number (a real
        # site-side cap — stock or a promo limit — rather than the one-time modal), this
        # stops there and reports that lower amount as the successful add, rather than
        # looping or failing outright: a partial weight in the cart is more useful than
        # none, and matches the same "report reality" spirit as raising
        # QuantityNotConfirmedError does on the whole-unit path above, just resolved as a
        # success here per explicit product decision (see module docstring) instead of
        # an error, since there is no way to represent an exact weight on this site at all.
        plus_btn = match.locator.locator("button.btn-acc.plus")
        qty_display = match.locator.locator(".num-span")
        close_popup = page.locator("#close-popup")

        confirmed = 0.0
        for _ in range(20):  # site's own step is ~0.5kg; 20 clicks covers up to ~10kg
            if confirmed >= quantity:
                break
            await match.locator.hover()
            await plus_btn.wait_for(state="visible", timeout=5000)
            await plus_btn.click()
            if await close_popup.count() > 0 and await close_popup.is_visible():
                await close_popup.click()
            new_confirmed = float((await qty_display.inner_text()).strip())
            if new_confirmed == confirmed:
                break
            confirmed = new_confirmed
        return confirmed

    async def get_cart_url(self, page: Page) -> str | None:
        return f"{BASE_URL}/cart"
