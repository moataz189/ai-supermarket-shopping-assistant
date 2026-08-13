"""Unit tests for RamiLevyAdapter's add_to_cart branching logic, against a minimal fake
Playwright locator tree that never touches a real browser or the real site.

This adapter is real-DOM/locator-driven (unlike Shufersal's fetch-based adapter), and its
selectors were verified against the real live site by hand (see the module docstring for
the full history) rather than exercised by an automated mock-site suite — that boundary is
unchanged here. What's new and testable in isolation is the *decision* logic added for
recipe-quantity awareness (weight vs. count-unit classification, the
QuantityConversionRequiredError case, and the one-time delivery-modal dismissal now
shared by both the weighed and whole-unit click paths) — this fake is just enough DOM to
exercise exactly that, calibrated against real, live-confirmed site behavior:
- a weighed tile has a `span[aria-label="לקילו גרם"]` marker and a `.num-span` that
  increases by a fixed step per click (confirmed live: 0.5 for tomato/cucumber, though
  never assumed to be 0.5 specifically — see FakeWeighedTile's configurable `step`)
- a whole-unit tile has no such marker and its `.num-span` increases by exactly 1 per click
- the very first click of a fresh session shows a `#close-popup`-dismissible modal on the
  `page`, regardless of which kind of tile triggered it (confirmed live, CP9 2026-08-08)
"""

import pytest

from mcp_servers.retailer_cart_mcp.adapters.rami_levy import RamiLevyAdapter
from mcp_servers.retailer_cart_mcp.automation import (
    MatchResult,
    QuantityNotConfirmedError,
    UnsupportedQuantityError,
)
from mcp_servers.retailer_cart_mcp.quantity import QuantityConversionRequiredError


class _AlwaysCountLocator:
    """A `.locator(selector)` result that just always reports "not present" — used for
    any selector this fake doesn't care to simulate specifically (e.g. the weight-marker
    span on a whole-unit tile)."""

    async def count(self):
        return 0

    async def is_visible(self):
        return False


class _PlusButton:
    def __init__(self, tile: "FakeTile"):
        self._tile = tile

    async def wait_for(self, state="visible", timeout=5000):
        pass

    async def click(self, force=False):
        self._tile.confirmed = round(self._tile.confirmed + self._tile.step, 6)
        self._tile.clicks += 1


class _NumSpan:
    def __init__(self, tile: "FakeTile"):
        self._tile = tile

    async def inner_text(self):
        # Site renders whole steps without a decimal point (e.g. "1", not "1.0") —
        # mirrored here since the adapter parses this via float(), which handles both.
        value = self._tile.confirmed
        return str(int(value)) if value == int(value) else str(value)


class FakeTile:
    """Simulates a single product tile: `step` is how much `.num-span` increases per
    click (1 for a whole-unit product; a real weighed product's own discovered
    kg-per-click for a weighed one). `is_weighed` controls whether the
    `span[aria-label="לקילו גרם"]` marker is present."""

    def __init__(self, *, is_weighed: bool, step: float = 1.0):
        self.is_weighed = is_weighed
        self.step = step
        self.confirmed = 0.0
        self.clicks = 0

    async def hover(self):
        pass

    def locator(self, selector: str):
        if selector == 'span[aria-label="לקילו גרם"]':
            return _WeightMarkerLocator(self.is_weighed)
        if selector == "button.btn-acc.plus":
            return _PlusButton(self)
        if selector == ".num-span":
            return _NumSpan(self)
        raise AssertionError(f"unexpected tile selector: {selector}")


class _WeightMarkerLocator:
    def __init__(self, present: bool):
        self._present = present

    async def count(self):
        return 1 if self._present else 0


class FakePage:
    """`show_modal_on_first_click` simulates the real site's one-time delivery-area
    modal that appears after the session's very first add-to-cart click of any kind."""

    def __init__(self, *, show_modal_on_first_click: bool = False):
        self._show_modal_on_first_click = show_modal_on_first_click
        self._modal_shown_once = False
        self.close_popup_clicks = 0

    def locator(self, selector: str):
        if selector == "#close-popup":
            return _ClosePopup(self)
        return _AlwaysCountLocator()


class _ClosePopup:
    def __init__(self, page: FakePage):
        self._page = page

    async def count(self):
        return 1 if self._should_show() else 0

    async def is_visible(self):
        return self._should_show()

    async def click(self):
        self._page._modal_shown_once = True
        self._page.close_popup_clicks += 1

    def _should_show(self) -> bool:
        return self._page._show_modal_on_first_click and not self._page._modal_shown_once


def _match(tile: FakeTile, item_code: str = "X1") -> MatchResult:
    return MatchResult(item_code=item_code, locator=tile, matched_by="exact_name")


async def test_weighed_item_legacy_no_unit_treats_quantity_as_kg_directly():
    tile = FakeTile(is_weighed=True, step=0.5)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 1)

    assert result.quantity == pytest.approx(1.0)
    assert result.unit == "kg"
    assert tile.clicks == 2  # 0.5 -> 1.0


async def test_weighed_item_grams_normalizes_and_rounds_up_to_step():
    tile = FakeTile(is_weighed=True, step=0.5)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 400, "g")

    assert result.quantity == pytest.approx(0.5)
    assert result.unit == "kg"
    assert tile.clicks == 1


async def test_weighed_item_600g_rounds_up_to_one_kg():
    tile = FakeTile(is_weighed=True, step=0.5)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 600, "g")

    assert result.quantity == pytest.approx(1.0)


async def test_weighed_item_1_1kg_rounds_up_to_1_5kg():
    tile = FakeTile(is_weighed=True, step=0.5)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 1.1, "kg")

    assert result.quantity == pytest.approx(1.5)


async def test_weighed_item_530g_rounds_up_to_one_kg_with_half_kg_increment():
    tile = FakeTile(is_weighed=True, step=0.5)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 530, "g")

    assert result.quantity == pytest.approx(1.0)
    assert result.unit == "kg"


async def test_weighed_item_500g_stays_at_half_kg_no_rounding_down_and_no_extra_step():
    tile = FakeTile(is_weighed=True, step=0.5)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 500, "g")

    assert result.quantity == pytest.approx(0.5)
    assert tile.clicks == 1  # exactly one 0.5 kg step, never rounded up past the boundary


async def test_weighed_item_501g_rounds_up_to_one_kg_never_down():
    tile = FakeTile(is_weighed=True, step=0.5)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 501, "g")

    assert result.quantity == pytest.approx(1.0)
    # A short add (0.5 kg for a 501 g request) would leave the recipe short -- the
    # confirmed cart quantity must always be >= what was requested, converted to kg.
    assert result.quantity >= 0.501


async def test_weighed_item_with_count_unit_raises_quantity_conversion_required():
    tile = FakeTile(is_weighed=True, step=0.5)
    page = FakePage()

    with pytest.raises(QuantityConversionRequiredError) as exc_info:
        await RamiLevyAdapter().add_to_cart(page, _match(tile), 2, "unit")

    assert exc_info.value.requested_quantity == 2
    assert exc_info.value.requested_unit == "unit"
    assert exc_info.value.retailer_selling_method == "by_weight"
    assert tile.clicks == 0  # never attempted a guessed add


async def test_whole_unit_item_with_count_unit_uses_recipe_count_directly():
    # e.g. "3 eggs" (Spoonacular unit "large") -> quantity 3, not replaced with 1.
    tile = FakeTile(is_weighed=False, step=1.0)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 3, "large")

    assert result.quantity == 3
    assert result.unit == "unit"
    assert tile.clicks == 3


async def test_whole_unit_item_with_weight_unit_buys_one_whole_package():
    tile = FakeTile(is_weighed=False, step=1.0)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 250, "g")

    assert result.quantity == 1
    assert result.unit == "unit"
    assert tile.clicks == 1


async def test_whole_unit_item_with_weight_unit_buys_enough_whole_packages_when_size_known():
    # Reproduces a real bug: a recipe needing 1000 g of pasta, matched to a 500 g
    # package, previously bought only 1 package (500 g).
    tile = FakeTile(is_weighed=False)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(
        page, _match(tile), 1000, "g", package_size=500.0, package_unit="g"
    )

    assert result.quantity == pytest.approx(2.0)
    assert result.unit == "unit"
    assert tile.clicks == 2


async def test_whole_unit_item_with_weight_unit_still_buys_one_package_when_size_unknown():
    # No package_size/package_unit given -- unchanged legacy behavior.
    tile = FakeTile(is_weighed=False)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 1000, "g")

    assert result.quantity == pytest.approx(1.0)
    assert tile.clicks == 1


async def test_whole_unit_item_with_weight_unit_buys_one_package_when_size_is_not_comparable():
    # package_unit is "unit" (a count, not a real weight/volume) -- packages_needed
    # returns None, falls back to the safe "buy 1" default rather than guessing.
    tile = FakeTile(is_weighed=False)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(
        page, _match(tile), 1000, "g", package_size=1.0, package_unit="unit"
    )

    assert result.quantity == pytest.approx(1.0)
    assert tile.clicks == 1


async def test_legacy_whole_unit_call_without_unit_is_unchanged():
    tile = FakeTile(is_weighed=False, step=1.0)
    page = FakePage()

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 2)

    assert result.quantity == 2
    assert result.unit == "unit"


async def test_legacy_fractional_whole_unit_quantity_still_rejected():
    tile = FakeTile(is_weighed=False, step=1.0)
    page = FakePage()

    with pytest.raises(UnsupportedQuantityError):
        await RamiLevyAdapter().add_to_cart(page, _match(tile), 1.5)


async def test_legacy_site_side_cap_still_reported_as_mismatch():
    tile = FakeTile(is_weighed=False, step=0.0)  # site refuses to move past 0
    page = FakePage()

    with pytest.raises(QuantityNotConfirmedError, match="requested 2 .* shows 0"):
        await RamiLevyAdapter().add_to_cart(page, _match(tile), 2)


async def test_first_click_modal_is_dismissed_for_whole_unit_multi_click_add():
    # Real bug this test pins down: a whole-unit item's 2nd+ click used to hang/timeout
    # if the site's one-time delivery modal appeared after the 1st click, since only the
    # weighed-item path originally handled dismissing it.
    tile = FakeTile(is_weighed=False, step=1.0)
    page = FakePage(show_modal_on_first_click=True)

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 3, "large")

    assert result.quantity == 3
    assert page.close_popup_clicks == 1  # dismissed exactly once, not once per click


async def test_first_click_modal_is_dismissed_for_weighed_item_add():
    tile = FakeTile(is_weighed=True, step=0.5)
    page = FakePage(show_modal_on_first_click=True)

    result = await RamiLevyAdapter().add_to_cart(page, _match(tile), 1)

    assert result.quantity == pytest.approx(1.0)
    assert page.close_popup_clicks == 1
