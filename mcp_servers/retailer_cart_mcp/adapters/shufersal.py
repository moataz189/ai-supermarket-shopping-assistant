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

`search_and_match` searches by `item_code` first, before ever searching by name — confirmed
live (CP9 follow-up, 2026-08-06 then 2026-08-07) that our locally-ingested catalog's
item_codes are genuine retailer barcodes/GTINs that match the site's own product codes
one-for-one, and that the site's search engine treats a bare numeric query as an exact
barcode lookup (no `P_` prefix — confirmed live that a prefixed query breaks into an
unrelated substring match). This isn't just about matching results more reliably than name
comparison (our feed's raw `ItemName` — e.g. brand/size concatenated with no spaces —
frequently differs from the site's own cleaner display name for the identical product): a
*name* search can return several genuinely different products sharing the exact same
display name (confirmed live: 10 distinct products all named "לחם אחיד פרוס"), so even
exact-name matching is ambiguous in a way code matching never is. Only falls back to a name
search (then exact-name, then first-result) when there's no item_code, or the code search
itself finds nothing.

**A real user report of "confirmed added but not visible in my account" was investigated
at length (CP9 follow-up, 2026-08-06) and root-caused to something outside this adapter
entirely, not a bug here.** Ruled out concretely, in order: name matching (fixed above
regardless, but not the cause), session/account identity (a same-account, freshly captured
session still didn't appear to show it), and request shape (a genuine Playwright `.click()`
on the real "add to cart" button was captured and compared byte-for-byte against this
adapter's `ajaxCall` request — effectively identical, both landed the same way). The actual
cause: the user was checking an **already-open, already-logged-in browser tab**, which
doesn't refetch true server-side account state from a page load or a link click — only a
fresh login (log out, log back in) forces it to. The add was genuinely reaching the real,
cross-device account cart the whole time; confirmed once the user did a fresh login. No
adapter behavior change resulted from this beyond the `item_code`-matching and
`get_cart_url` fixes above, both good independently but neither was the actual cause of
what looked like a failure.

No login/checkout/payment method exists here or anywhere in this adapter, by construction.
No bot-evasion, CAPTCHA-bypass, or fingerprint-spoofing is implemented — a detected block is
always reported and the run stops gracefully; it is never worked around.

**Recipe-quantity-aware add_to_cart (CP9 follow-up, 2026-08-08).** `unit=None` (the
default) is the legacy path — behavior byte-identical to before this parameter existed.
When a recipe supplies a real `unit`: a `BY_WEIGHT` product gets the recipe's weight
normalized straight to kg and sent as-is — confirmed live that this site's `/cart/add`
takes an exact kg float with no minimum-increment rounding at all (a request for 0.4 kg
came back confirmed as exactly 0.4), unlike Rami Levy's DOM stepper, which only moves in
fixed steps. A count-like unit (e.g. "large", "unit") against a `BY_UNIT`/`BY_PACKAGE`
product uses the recipe's count directly. A weight/volume unit against a `BY_UNIT`/
`BY_PACKAGE` product (e.g. "250 g pasta") buys one whole package, the ordinary way people
shop for packaged goods, rather than inventing a package count from an amount with no
known per-product size. Only the genuinely incompatible case — a non-weight unit (a bare
count, or a volume with no density source) against a `BY_WEIGHT` product — raises
`QuantityConversionRequiredError` instead of guessing.
"""

from urllib.parse import quote

from playwright.async_api import Page

from mcp_servers.retailer_cart_mcp.automation import (
    MatchResult,
    QuantityNotConfirmedError,
    UnsupportedSiteFlowError,
)
from mcp_servers.retailer_cart_mcp.quantity import (
    AddToCartResult,
    QuantityConversionRequiredError,
    is_count_unit,
    normalize_weight_to_kg,
)

BASE_URL = "https://www.shufersal.co.il"


def _find_by_code(results: list[dict], normalized_code: str) -> MatchResult | None:
    for item in results:
        site_code = (item.get("code") or "").removeprefix("P_")
        if site_code == normalized_code:
            return MatchResult(item_code=item["code"], locator=item, matched_by="item_code")
    return None


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
        # Searches by item_code FIRST when we have one — confirmed live (CP9 follow-up,
        # 2026-08-07) that the site's search engine treats a bare numeric code as an exact
        # barcode lookup (query = the digits only, no "P_" prefix — confirmed live that a
        # prefixed query breaks into an unrelated substring match across the whole
        # catalog). This isn't just an optimization: a name search for "לחם אחיד פרוס" (a
        # generic bread name) returned 10 *different* products sharing that exact name —
        # exact-name matching is ambiguous in real product catalogs in a way code matching
        # never is. Only falls back to a name search if code search finds nothing, or there
        # is no item_code to search by at all.
        #
        # One navigation per fresh context (automation.py gives each item its own), then
        # the rest of this adapter talks to the site entirely through same-origin fetch
        # calls from inside page.evaluate() — no further navigation is needed at all.
        await page.goto(BASE_URL)

        normalized_code = item_code.removeprefix("P_") if item_code else None
        if normalized_code:
            code_results = await self._search(page, normalized_code)
            match = _find_by_code(code_results, normalized_code)
            if match is not None:
                return match

        results = await self._search(page, item_name)
        if not results:
            return None

        if normalized_code:
            match = _find_by_code(results, normalized_code)
            if match is not None:
                return match

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

    async def add_to_cart(
        self, page: Page, match: MatchResult, quantity: float, unit: str | None = None
    ) -> AddToCartResult:
        item = match.locator
        selling_method = (item.get("sellingMethod") or {}).get("code", "BY_UNIT")
        is_weighed = selling_method == "BY_WEIGHT"

        if unit is None:
            # Legacy request (no recipe unit) — unchanged from before `unit` existed.
            send_qty, result_unit = quantity, ("kg" if is_weighed else "unit")
        elif is_weighed:
            target_kg = normalize_weight_to_kg(quantity, unit)
            if target_kg is None:
                raise QuantityConversionRequiredError(
                    f"{match.item_code} is sold by weight (kg); {quantity} {unit} has no "
                    "deterministic weight conversion",
                    requested_quantity=quantity,
                    requested_unit=unit,
                    retailer_selling_method=selling_method,
                )
            # Confirmed live (CP9 2026-08-08): this site's /cart/add takes an exact kg
            # float with no minimum-increment rounding at all — a request for 0.4 was
            # confirmed back as exactly 0.4, unlike Rami Levy's DOM stepper (0.5kg steps),
            # so there is nothing to round up to here; the recipe's own weight is used as-is.
            send_qty, result_unit = target_kg, "kg"
        elif is_count_unit(unit):
            send_qty, result_unit = quantity, "unit"
        else:
            # Recipe gave a weight/volume for a product this retailer sells as a whole
            # package/unit (e.g. "250 g pasta" -> one box of pasta) — buy one of it, same
            # as ordinary packaged-goods shopping, rather than inventing a package count
            # from an amount with no per-product package size available to convert with.
            send_qty, result_unit = 1, "unit"

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
                {"productCode": match.item_code, "sellingMethod": selling_method, "qty": send_qty},
            )
        except Exception as exc:
            raise UnsupportedSiteFlowError(f"/cart/add call failed: {exc}") from exc

        confirmed = await self._confirm_quantity(page, item.get("name", ""), match.item_code)
        if confirmed != send_qty:
            raise QuantityNotConfirmedError(
                f"requested {send_qty} for {match.item_code}, site cart shows {confirmed}"
            )
        return AddToCartResult(confirmed, result_unit)

    async def get_cart_url(self, page: Page) -> str | None:
        # `/online/he/cart` is NOT a real route on this site — confirmed live, CP9
        # follow-up (2026-08): navigating there directly (fresh context, no referrer)
        # redirects to a generic fallback page (`/online/he/A?null`) with no cart content
        # at all. There is no dedicated, directly-linkable cart page here: the real cart is
        # a client-side flyout (`#cartContainer`) that only renders after the header "הסל
        # שלי" trigger (a `javascript:void(0)` link, not a URL) is clicked on an
        # already-loaded page. The best honest link is the site's own homepage, where the
        # user can click that trigger themselves once logged in.
        return f"{BASE_URL}/online/he/"
