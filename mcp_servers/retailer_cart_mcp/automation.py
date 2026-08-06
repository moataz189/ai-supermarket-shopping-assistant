from dataclasses import dataclass
from typing import Any, Protocol

from playwright.async_api import Page, async_playwright


class UnsupportedQuantityError(Exception):
    """Raised by an adapter when the requested quantity can't be represented on the site
    (e.g. a fractional quantity for a product the retailer only sells in whole units).
    Adapters must raise this explicitly rather than silently rounding or truncating."""


class QuantityNotConfirmedError(Exception):
    """Raised by an adapter when the cart quantity it reads back after add-to-cart doesn't
    match what was requested (site-side cap, stock limit, a UI update that didn't take)."""


class UnsupportedSiteFlowError(Exception):
    """Raised by an adapter when it depends on an internal, undocumented site interface
    (an internal JS helper, an XHR endpoint) that isn't available or doesn't behave as
    expected on this page load — e.g. the site removed/renamed the function, or an
    endpoint's response shape changed. This is expected to happen eventually since the
    interface is undocumented and can change without notice; adapters must report it as a
    structured failure rather than falling back to guessing, force-clicking, or otherwise
    working around the missing interface."""


@dataclass
class MatchResult:
    item_code: str
    locator: Any
    matched_by: str  # "item_code" | "exact_name" | "name_fallback"


class RetailerAdapter(Protocol):
    """No login/checkout/payment method exists here, by construction — the orchestration
    loop below only ever calls the five methods declared on this protocol."""

    retailer_name: str

    async def open_site(self, page: Page) -> None: ...
    async def detect_block(self, page: Page) -> str | None: ...
    async def search_and_match(self, page: Page, item_name: str, item_code: str) -> MatchResult | None:
        """Finds the best match for (item_name, item_code): an exact item_code/barcode
        match first, an exact product-name match as fallback, then a weaker name-based
        match only if nothing else matched. Returns None if nothing matched at all."""
        ...

    async def add_to_cart(self, page: Page, match: MatchResult, quantity: float) -> float:
        """Adds the matched product to the cart, sets its quantity to `quantity`, and
        returns the quantity actually confirmed on the site. Raises UnsupportedQuantityError
        or QuantityNotConfirmedError (or lets any other exception propagate) if the
        requested quantity can't be confirmed."""
        ...

    async def get_cart_url(self, page: Page) -> str | None: ...


async def _safe_detect_block(adapter: RetailerAdapter, page: Page) -> str | None:
    try:
        return await adapter.detect_block(page)
    except Exception as exc:
        # A block detector that itself errors is treated as a block: we can no longer
        # tell whether it's safe to continue, and continuing unchecked risks driving the
        # browser somewhere unintended (e.g. toward checkout).
        return f"block_detection_error: {exc}"


def _mark_skipped(items: list[dict], added: list[dict], failed: list[dict]) -> None:
    handled = {r["item_code"] for r in added} | {r["item_code"] for r in failed}
    for remaining in items:
        if remaining["item_code"] not in handled:
            failed.append({
                "name": remaining["name"],
                "item_code": remaining["item_code"],
                "status": "error",
                "reason": "skipped_after_block",
            })


async def prepare_cart_for_retailer(
    adapter: RetailerAdapter, items: list[dict], storage_state_path: str | None = None
) -> dict:
    added: list[dict] = []
    failed: list[dict] = []
    blocked_reason: str | None = None
    cart_url: str | None = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(storage_state=storage_state_path)
            page = await context.new_page()

            try:
                await adapter.open_site(page)
                blocked_reason = await _safe_detect_block(adapter, page)
            except Exception as exc:
                blocked_reason = f"site_open_failed: {exc}"

            if blocked_reason is None:
                for item in items:
                    name, item_code, quantity = item["name"], item["item_code"], item["quantity"]

                    # A fresh context per item — not the shared `page` used for
                    # open_site()/get_cart_url() above — reloading the same
                    # storage_state. Reusing one page/context across multiple full
                    # navigations left at least one real site's add-to-cart button
                    # permanently hidden after the context's first navigation (confirmed
                    # live against Shufersal, CP9: reproduced 8 ways, root-caused to a
                    # context-scoped personalization/analytics script that only
                    # initializes certain widgets correctly on that context's first page
                    # load — a fresh context per item sidesteps it, since each one gets
                    # its own first-and-only navigation).
                    item_context = None
                    try:
                        item_context = await browser.new_context(storage_state=storage_state_path)
                        item_page = await item_context.new_page()

                        try:
                            match = await adapter.search_and_match(item_page, name, item_code)
                        except Exception as exc:
                            failed.append({"name": name, "item_code": item_code, "status": "error", "reason": str(exc)})
                            continue

                        blocked_reason = await _safe_detect_block(adapter, item_page)
                        if blocked_reason:
                            break

                        if match is None:
                            failed.append({"name": name, "item_code": item_code, "status": "not_found"})
                            continue

                        try:
                            confirmed_qty = await adapter.add_to_cart(item_page, match, quantity)
                        except Exception as exc:
                            failed.append({"name": name, "item_code": item_code, "status": "error", "reason": str(exc)})
                            continue

                        added.append({
                            "name": name,
                            "item_code": item_code,
                            "status": "added",
                            "matched_by": match.matched_by,
                            "quantity_confirmed": confirmed_qty,
                        })

                        blocked_reason = await _safe_detect_block(adapter, item_page)
                        if blocked_reason:
                            break
                    finally:
                        if item_context is not None:
                            await item_context.close()

            _mark_skipped(items, added, failed)

            if blocked_reason is None:
                blocked_reason = await _safe_detect_block(adapter, page)
                _mark_skipped(items, added, failed)

            if blocked_reason is None:
                try:
                    cart_url = await adapter.get_cart_url(page)
                except Exception:
                    cart_url = None
        finally:
            await browser.close()

    return {
        "retailer": adapter.retailer_name,
        "added": added,
        "failed": failed,
        "blocked": blocked_reason is not None,
        "blocked_reason": blocked_reason,
        "cart_url": cart_url,
    }
