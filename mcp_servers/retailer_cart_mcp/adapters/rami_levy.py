"""Adapter for rami-levy.co.il. Not exercised by the mock-site suite (those run against
tests/mcp/mock_site_server.py) — this site's structure is not assumed to match
Shufersal's (see shufersal.py) and is implemented independently. The real-DOM
selectors/mechanics below are verified live by hand rather than by an automated mock
site (see history below); the *decision* logic added for recipe-quantity awareness is
unit-tested in isolation against a fake locator tree in tests/mcp/test_rami_levy_adapter.py.

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
  own fixed weight step (0.5), not a whole "1". `add_to_cart` detects the
  `span[aria-label="לקילו גרם"]` marker and routes to `_add_weighed_item` instead of the
  whole-unit stepper path. This is deliberately generic (the marker, not a name/category
  allowlist), so it applies to any weight-sold product, not just tomatoes.
- A packaged bread item reported `QuantityNotConfirmedError` ("requested 1 ... site shows
  2.0") on one run but not on repeated live re-checks of the same product/click sequence
  immediately after (which consistently confirmed "1"). Left as-is: the whole-unit path
  still never silently accepts a site-confirmed quantity that doesn't match what was
  requested, so a stale promo/pack-size default or a one-off UI quirk surfaces as an
  honest, reported mismatch rather than a silent wrong add — unlike the weighed-produce
  case above, there's no known, generic site-side reason a whole-unit item wouldn't
  confirm the exact requested count.

**Recipe-quantity-aware add_to_cart (CP9 follow-up, 2026-08-08).** `unit=None` (the
default) is the legacy path for both the weighed and whole-unit branches, byte-identical
to before this parameter existed (a weighed item's `quantity` is treated as already being
in kg, exactly like the original click-until-reach-1kg behavior). When a recipe supplies a
real `unit`: a weighed product's requested amount is normalized to kg
(mcp_servers/retailer_cart_mcp/quantity.py's `normalize_weight_to_kg`) and rounded up to
this product's own click-step (`round_up_to_increment` — discovered empirically from the
first click's own delta, never hardcoded, since the site exposes no step size as data
anywhere); a count-like unit (e.g. "large", "unit") on a whole-unit product uses the
recipe's count directly (e.g. "3 large" eggs -> 3 clicks); a weight/volume unit on a
whole-unit product (e.g. "250 g pasta") buys one whole package, the ordinary way people
shop for packaged goods, rather than inventing a package count with no known per-product
size. Only the genuinely incompatible case — a non-weight unit against a weighed product,
e.g. "2 units" of something sold only by kg — raises `QuantityConversionRequiredError`
instead of guessing a conversion.

**The one-time delivery-area modal is not weight-specific.** Originally discovered only
on a weighed item and assumed to be part of that flow; a later live run of a *whole-unit*
multi-click add (3 clicks) hung on its 2nd click the exact same way. Root-caused to the
same one-time `#delivery-modal`/`#close-popup` gate triggered by a session's very first
add-to-cart click of any kind — `_click_plus_and_dismiss_first_click_modal` is now shared
by both the weighed and whole-unit click paths so neither can hang on it.

No login/checkout/payment method exists here or anywhere in this adapter, by construction.
No bot-evasion, CAPTCHA-bypass, or fingerprint-spoofing is implemented — a detected block is
always reported and the run stops gracefully; it is never worked around.

**Item_code-based search added (CP9 follow-up, 2026-08-08), correcting an earlier
untested assumption.** This adapter previously never searched by `item_code` at all,
reasoning that "the real site doesn't expose our fixture-style item_code on search
tiles" — true for the *fixture's* fake codes, but never actually tested against a real
barcode. Root-caused live, after a real item's full-exact-name search still returned
`not_found` even with a correct, live-verified product name in the fixture: searching
Rami Levy's real site with that same product's *full* name as the query doesn't reliably
surface that exact tile among the results (shorter/partial queries do) — a
search-relevance quirk distinct from anything about matching itself. Separately
confirmed live that querying with a *real barcode* returns only that product's tile(s),
while a nonexistent one returns zero — so `search_and_match` now tries item_code first,
exactly like Shufersal's adapter, sidestepping the full-name query problem entirely for
any item with a real code.
"""

from urllib.parse import quote

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from mcp_servers.retailer_cart_mcp.automation import (
    MatchResult,
    QuantityNotConfirmedError,
    UnsupportedQuantityError,
)
from mcp_servers.retailer_cart_mcp.quantity import (
    AddToCartResult,
    QuantityConversionRequiredError,
    is_count_unit,
    normalize_weight_to_kg,
    packages_needed,
    round_up_to_increment,
)

BASE_URL = "https://www.rami-levy.co.il"


async def _click_plus_and_dismiss_first_click_modal(page: Page, tile, plus_btn) -> None:
    """A session's very first add-to-cart click of ANY kind — whole-unit or weighed —
    triggers a one-time "delivery area" modal (#delivery-modal) that blocks all further
    page interaction until dismissed via its #close-popup button. Confirmed live, CP9
    2026-08-08: initially found only on a weighed item and assumed weight-specific, but a
    later live run showed a *whole-unit* multi-click add hang on its 2nd click the exact
    same way — root cause is the same one-time modal, not something particular to weighed
    products. Every click after the first (of the whole session, regardless of which
    product triggered it) closes cleanly with no modal, so this is always checked but
    normally a no-op after the first call across an entire add_to_cart run."""
    await tile.hover()
    await plus_btn.wait_for(state="visible", timeout=5000)
    await plus_btn.click()
    close_popup = page.locator("#close-popup")
    if await close_popup.count() > 0 and await close_popup.is_visible():
        await close_popup.click()


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
        # Searches by item_code FIRST when we have one (CP9 follow-up, 2026-08-08) —
        # confirmed live that the real site's own search DOES support an exact barcode
        # lookup: querying a real product's barcode returns only that product's tile(s);
        # querying a nonexistent/fake one returns zero results. This corrects an earlier,
        # untested assumption in this adapter ("the real site doesn't expose item_code on
        # search tiles") that turned out to be an artifact of testing with fixture-style
        # fake codes, not an actual site limitation — the real barcode simply wasn't being
        # tried. As with Shufersal's equivalent code-first search, a non-empty result for
        # a barcode query is trusted directly (no further name check): the site itself is
        # doing the disambiguation, the same way a real barcode scanner would.
        if item_code:
            await page.goto(f"{BASE_URL}/he/online/search?q={quote(item_code)}")
            await _wait_for_tiles_hydrated(page)
            code_images = page.locator(".product-img img[alt]")
            if await code_images.count() > 0:
                tile = code_images.first.locator(
                    "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' big-plus-minus ')][1]"
                )
                return MatchResult(item_code=item_code, locator=tile, matched_by="item_code")

        # Falls back to a name search if code search finds nothing, or there is no
        # item_code to search by at all — but only an *exact* name match is accepted (no
        # "just take the first search result" fallback — removed CP9 follow-up,
        # 2026-08-08). Confirmed live on Shufersal's adapter (same fallback pattern) that
        # guessing the top, non-deterministically ranked search result for a real product
        # name can add a genuinely wrong product to a real cart — our local catalog's
        # item_name comes from a fixture-derived dataset, not the live site's own data,
        # so a legitimately unmatched item is possible and must be reported as such, not
        # guessed at.
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

        return None

    async def add_to_cart(
        self, page: Page, match: MatchResult, quantity: float, unit: str | None = None,
        *, package_size: float | None = None, package_unit: str | None = None,
    ) -> AddToCartResult:
        # Loose/weighed produce (marked "לק"ג" — "per kg" — on the tile, confirmed live,
        # CP9 2026-08-08) doesn't behave like a normal whole-unit stepper: each click adds
        # the site's own fixed weight step (observed: 0.5) rather than a whole "1" — so
        # this clicks repeatedly until the target weight is reached (see _add_weighed_item).
        is_weighed = await match.locator.locator('span[aria-label="לקילו גרם"]').count() > 0

        if is_weighed:
            if unit is None:
                # Legacy request (no recipe unit) — `quantity` is treated as already
                # being in kg, unchanged from before `unit` existed.
                target_kg = quantity
            else:
                target_kg = normalize_weight_to_kg(quantity, unit)
                if target_kg is None:
                    raise QuantityConversionRequiredError(
                        f"{match.item_code} is sold by weight (kg); {quantity} {unit} has no "
                        "deterministic weight conversion",
                        requested_quantity=quantity,
                        requested_unit=unit,
                        retailer_selling_method="by_weight",
                    )
            confirmed = await self._add_weighed_item(page, match, target_kg)
            return AddToCartResult(confirmed, "kg")

        # Whole-unit stepper path. No direct-fill quantity input on this site — only a
        # stepper (+/- buttons showing a running count), so only whole-unit quantities
        # are representable.
        if unit is not None and not is_count_unit(unit):
            # Recipe gave a weight/volume for a product this retailer sells as a whole
            # package/unit (e.g. "1000 g pasta" against a 500 g box) -- buy enough whole
            # packages to cover the real requested amount when this matched product's
            # own package size is known (from the local catalog) and comparable;
            # otherwise fall back to buying just one, the ordinary way people shop for
            # packaged goods, rather than inventing a package count with no known
            # per-product size to convert with.
            count = None
            if package_size is not None and package_unit is not None:
                count = packages_needed(quantity, unit, package_size, package_unit)
            unit_count = count or 1
        else:
            if quantity != int(quantity):
                raise UnsupportedQuantityError(
                    f"Rami Levy only supports whole-unit quantities, got {quantity}"
                )
            unit_count = int(quantity)

        plus_btn = match.locator.locator("button.btn-acc.plus")
        qty_display = match.locator.locator(".num-span")
        for _ in range(unit_count):
            await _click_plus_and_dismiss_first_click_modal(page, match.locator, plus_btn)

        confirmed = float((await qty_display.inner_text()).strip())
        if confirmed != unit_count:
            raise QuantityNotConfirmedError(
                f"requested {unit_count} for {match.item_code}, site shows {confirmed}"
            )
        return AddToCartResult(confirmed, "unit")

    async def _add_weighed_item(self, page: Page, match: MatchResult, target_kg: float) -> float:
        # The site exposes no per-product step size as data anywhere, so this discovers
        # it empirically from the first click's own delta (never hardcoded — generic
        # across any weighed product, not just tomatoes) and then uses
        # round_up_to_increment (mcp_servers/retailer_cart_mcp/quantity.py) — the same
        # ceil(requested/increment)*increment used everywhere else in this project — to
        # compute exactly how many more clicks reach the target. If a click ever DOESN'T
        # change the confirmed number (a real site-side cap — stock or a promo limit —
        # rather than the one-time modal handled by the click helper below), this stops
        # there and reports that lower amount as the successful add rather than looping
        # or failing: a partial weight in the cart is more useful than none, per explicit
        # product decision (see module docstring) — there is no way to represent an exact
        # arbitrary weight on this site's control regardless.
        plus_btn = match.locator.locator("button.btn-acc.plus")
        qty_display = match.locator.locator(".num-span")

        async def click_once() -> float:
            await _click_plus_and_dismiss_first_click_modal(page, match.locator, plus_btn)
            return float((await qty_display.inner_text()).strip())

        confirmed = await click_once()
        increment = confirmed  # first click's delta from 0 is this product's own step
        if increment <= 0:
            return confirmed  # nothing to scale by; report whatever the single click gave

        target = round_up_to_increment(target_kg, increment)
        remaining_clicks = round((target - confirmed) / increment)
        for _ in range(max(remaining_clicks, 0)):
            if confirmed >= target:
                break
            new_confirmed = await click_once()
            if new_confirmed == confirmed:
                break  # real site-side cap (stock/promo limit), not the one-time modal
            confirmed = new_confirmed
        return confirmed

    async def get_cart_url(self, page: Page) -> str | None:
        return f"{BASE_URL}/cart"
