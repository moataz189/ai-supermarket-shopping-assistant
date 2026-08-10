"""Implements RetailerAdapter against tests/mcp/mock_site_server.py's Flask app.

Mirrors what a real adapter (shufersal.py / rami_levy.py) does: search by item_code
first (barcode-style lookup), fall back to an exact product-name match — never trusting
the site to tell it which kind of match it got, and never guessing a "first search
result" beyond that (removed CP9 follow-up, 2026-08-08 — see the real adapters'
docstrings for why: it caused a real wrong-product add against a real cart).
"""

from mcp_servers.retailer_cart_mcp.automation import (
    AddToCartResult,
    MatchResult,
    QuantityNotConfirmedError,
    UnsupportedQuantityError,
)


class MockRetailerAdapter:
    retailer_name = "mock_retailer"

    def __init__(self, base_url: str):
        self.base_url = base_url

    async def open_site(self, page) -> None:
        await page.goto(self.base_url)

    async def detect_block(self, page) -> str | None:
        if await page.locator("[data-captcha]").count() > 0:
            return "captcha"
        if await page.locator("[data-login-wall]").count() > 0:
            return "login_required"
        return None

    async def search_and_match(self, page, item_name: str, item_code: str) -> MatchResult | None:
        await page.goto(f"{self.base_url}/search?q={item_code}")
        by_code = page.locator(f"[data-testid='product-tile'][data-item-code='{item_code}']")
        if await by_code.count() > 0:
            return MatchResult(item_code=item_code, locator=by_code.first, matched_by="item_code")

        await page.goto(f"{self.base_url}/search?q={item_name}")
        tiles = page.locator("[data-testid='product-tile']")
        count = await tiles.count()
        if count == 0:
            return None

        for i in range(count):
            tile = tiles.nth(i)
            name = await tile.get_attribute("data-name")
            if name is not None and name.lower() == item_name.lower():
                code = await tile.get_attribute("data-item-code")
                return MatchResult(item_code=code, locator=tile, matched_by="exact_name")

        return None

    async def add_to_cart(
        self, page, match: MatchResult, quantity: float, unit: str | None = None,
        *, package_size: float | None = None, package_unit: str | None = None,
    ) -> AddToCartResult:
        # This mock site doesn't simulate weight-sold products — `unit`/`package_size`/
        # `package_unit` are accepted (to satisfy the RetailerAdapter protocol used by
        # prepare_cart_for_retailer) but unused, exactly like both real adapters' legacy
        # (unit=None) whole-unit path.
        await match.locator.locator("[data-testid='add-to-cart']").click()

        await page.locator("input[name='quantity']").fill(str(quantity))
        await page.locator("[data-testid='update-quantity']").click()

        status = page.locator("[data-testid='cart-status']")
        error_attr = await status.get_attribute("data-error")
        if error_attr == "fractional_not_supported":
            raise UnsupportedQuantityError(
                f"{match.item_code} only supports whole-unit quantities, got {quantity}"
            )

        confirmed = float(await status.get_attribute("data-cart-qty"))
        if confirmed != quantity:
            raise QuantityNotConfirmedError(
                f"requested {quantity} for {match.item_code}, site shows {confirmed}"
            )
        return AddToCartResult(confirmed, "unit")

    async def get_cart_url(self, page) -> str | None:
        await page.goto(f"{self.base_url}/cart")
        return page.url
