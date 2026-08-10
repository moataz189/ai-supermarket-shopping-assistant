# Whole-Package Quantity Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a recipe needs a weight/volume amount of an ingredient (e.g. "1000 g pasta") but the matched product is sold as a whole fixed-size package (e.g. "500 g" pasta boxes, not sold loose by weight), buy enough whole packages to cover the real requested amount — never just one, regardless of how much is actually needed.

**Architecture:** Reproduced and root-caused live: a Rami Levy "פסטה פוזילי 500 גרם" (500 g pasta) product matched a recipe requesting 1000 g, but both adapters' existing "weight/volume unit against a whole-package product" branch unconditionally buys exactly 1 package — a deliberate simplification documented in both adapters' code precisely because, until now, the adapter had no way to know a specific matched product's real package size. It does exist, reliably: `RetailerProduct.package_size`/`.package_unit` are parsed directly from each retailer's real price-transparency feed (`Quantity`/`UnitOfMeasure`, see `app/ingestion/feeds/shufersal.py`'s `UNIT_MAP`) — e.g. this exact pasta is ingested as `package_size=500, package_unit="g"`. This plan threads that already-known package size from the local catalog (via `get_product_price`, already looked up during cart-building for the price itself) through `build_retailer_cart.py` → `prepare_retailer_cart.py` → the Retailer-Cart MCP → both adapters, where a new `packages_needed` helper (mirroring the existing `round_up_to_increment`'s "never round down" philosophy) computes how many whole packages are needed, falling back to the existing "buy 1" behavior whenever the package size is unknown or not a comparable weight/volume (fully backward compatible).

**Tech Stack:** Python 3, FastAPI, LangGraph, SQLAlchemy, pytest (`asyncio_mode = auto`), Playwright-backed retailer adapters (unit-tested against fake DOM/locator trees, never a real browser in the test suite).

## Global Constraints

- Never round down: the computed package count must always cover at least the requested amount, matching `round_up_to_increment`'s existing "never leave the recipe short" rule.
- `package_size`/`package_unit` are optional everywhere they're threaded (`None` by default) — every existing call site/test that doesn't supply them must keep behaving exactly as before (buy 1 whole package for the weight/volume-vs-whole-package mismatch case). This is a strict backward-compatibility requirement, not just a nicety.
- Only affects the specific "a weight/volume unit was requested, but the matched product is a whole-package product" branch in each adapter. The already-correct "weighed product" branch (`is_weighed`/`BY_WEIGHT`, using `round_up_to_increment`) and the "count unit against whole-package product" branch (e.g. "3 eggs") are untouched.
- `ruff check app tests mcp_servers` and `pytest` (`make lint` / `make test` / `make coverage`) must stay green; `cd web && npm run build` must stay green (no frontend changes expected — `RetailerCartResultView.tsx` already renders `cart_quantity`/`cart_unit` generically).
- Continue on the current branch `feature/budget-constrained-cart`, no worktree, no unrelated changes.

---

### Task 1: `packages_needed` — pure quantity-conversion helper

**Files:**
- Modify: `mcp_servers/retailer_cart_mcp/quantity.py`
- Test: Modify `tests/mcp/test_quantity.py`

**Interfaces:**
- Produces: `normalize_volume_to_l(quantity: float, unit: str) -> float | None` and `packages_needed(requested_quantity: float, requested_unit: str, package_size: float, package_unit: str) -> int | None` — consumed by Task 4 (both adapters).

- [ ] **Step 1: Write the failing tests**

Add to `tests/mcp/test_quantity.py` (new imports at the top, then new test classes at the end of the file):

```python
from mcp_servers.retailer_cart_mcp.quantity import (
    is_count_unit,
    normalize_volume_to_l,
    normalize_weight_to_kg,
    packages_needed,
    round_up_to_increment,
)
```

(Replaces the existing narrower import list at the top of the file — add `normalize_volume_to_l` and `packages_needed` to it.)

```python
class TestNormalizeVolumeToL:
    def test_milliliters_converts_to_liters(self):
        assert normalize_volume_to_l(500, "ml") == pytest.approx(0.5)

    def test_liters_passes_through(self):
        assert normalize_volume_to_l(1.5, "l") == pytest.approx(1.5)

    def test_long_forms_and_case_insensitive(self):
        assert normalize_volume_to_l(250, "Milliliters") == pytest.approx(0.25)
        assert normalize_volume_to_l(2, "Liters") == pytest.approx(2.0)

    def test_non_volume_unit_returns_none(self):
        assert normalize_volume_to_l(2, "g") is None
        assert normalize_volume_to_l(2, "cup") is None
        assert normalize_volume_to_l(2, "unit") is None


class TestPackagesNeeded:
    def test_1000g_needed_in_500g_packages_is_two(self):
        # Reproduces a real bug: a recipe needing 1000 g of pasta, matched to a 500 g
        # package, previously bought only 1 package (500 g) -- half of what's needed.
        assert packages_needed(1000, "g", 500, "g") == 2

    def test_exact_multiple_needs_exactly_that_many_packages(self):
        assert packages_needed(1000, "g", 500, "g") == 2
        assert packages_needed(500, "g", 500, "g") == 1

    def test_never_rounds_down_partial_package_still_needs_one_more(self):
        assert packages_needed(501, "g", 500, "g") == 2
        assert packages_needed(1001, "g", 500, "g") == 3

    def test_kg_and_g_units_are_compatible(self):
        assert packages_needed(1, "kg", 500, "g") == 2
        assert packages_needed(1.5, "kg", 0.5, "kg") == 3

    def test_ml_and_l_units_are_compatible(self):
        assert packages_needed(1500, "ml", 500, "ml") == 3
        assert packages_needed(1.5, "l", 500, "ml") == 3

    def test_at_least_one_package_even_for_a_tiny_request(self):
        assert packages_needed(10, "g", 500, "g") == 1

    def test_incompatible_dimensions_return_none(self):
        # A weight request against a package with no known weight/volume (e.g. a
        # count-based "unit" package), or vice versa -- callers must not guess.
        assert packages_needed(1000, "g", 1, "unit") is None
        assert packages_needed(500, "ml", 2, "unit") is None
        assert packages_needed(500, "g", 500, "ml") is None  # weight vs volume mismatch
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/moatazodeh/Documents/ai-supermarket-agent && source .venv/bin/activate && python -m pytest tests/mcp/test_quantity.py -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_volume_to_l'`.

- [ ] **Step 3: Implement in `mcp_servers/retailer_cart_mcp/quantity.py`**

Add after `normalize_weight_to_kg` (keep `_WEIGHT_TO_KG`/`_VOLUME_UNITS` and everything else unchanged):

```python
# Recognized volume units, normalized to a liter multiplier. Deliberately mirrors
# _WEIGHT_TO_KG's strictness (see normalize_weight_to_kg) -- only ml/l forms are
# deterministic; anything else (cup, tbsp, ...) has no fixed, ingredient-independent
# volume conversion and must not be guessed at here.
_VOLUME_TO_L = {
    "ml": 0.001,
    "milliliter": 0.001,
    "milliliters": 0.001,
    "millilitre": 0.001,
    "millilitres": 0.001,
    "l": 1.0,
    "liter": 1.0,
    "liters": 1.0,
    "litre": 1.0,
    "litres": 1.0,
}


def normalize_volume_to_l(quantity: float, unit: str) -> float | None:
    """Returns `quantity` expressed in liters if `unit` is a recognized volume unit
    (ml/l forms only), else None -- mirrors normalize_weight_to_kg's philosophy: an
    honest None for anything not deterministically convertible, never a guess."""
    factor = _VOLUME_TO_L.get(unit.strip().lower())
    return round(quantity * factor, 6) if factor is not None else None
```

Add after `round_up_to_increment`:

```python
def packages_needed(
    requested_quantity: float, requested_unit: str, package_size: float, package_unit: str
) -> int | None:
    """How many whole packages of `package_size` `package_unit` are needed to cover at
    least `requested_quantity` `requested_unit` (e.g. a recipe needing 1000 g of pasta,
    sold in 500 g packages, needs 2) -- never rounds down, so the recipe is never left
    short. Returns None when the two amounts aren't the same kind of quantity (a weight
    request against a package with no known weight/volume, a volume request against a
    weight-only package, etc.) -- callers must fall back to buying a single package
    rather than guessing a conversion in that case.
    """
    requested_kg = normalize_weight_to_kg(requested_quantity, requested_unit)
    package_kg = normalize_weight_to_kg(package_size, package_unit)
    if requested_kg is not None and package_kg is not None and package_kg > 0:
        return max(1, math.ceil(round(requested_kg / package_kg, 9)))

    requested_l = normalize_volume_to_l(requested_quantity, requested_unit)
    package_l = normalize_volume_to_l(package_size, package_unit)
    if requested_l is not None and package_l is not None and package_l > 0:
        return max(1, math.ceil(round(requested_l / package_l, 9)))

    return None
```

`math` is already imported at the top of this file (used by `round_up_to_increment`) — no new import needed there.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/mcp/test_quantity.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp_servers/retailer_cart_mcp/quantity.py tests/mcp/test_quantity.py
git commit -m "feat(retailer-cart-mcp): add packages_needed for whole-package weight/volume coverage"
```

---

### Task 2: Expose `package_size`/`package_unit` from `get_product_price`

**Files:**
- Modify: `mcp_servers/supermarket_mcp/schemas.py`
- Modify: `mcp_servers/supermarket_mcp/server.py`
- Test: Modify `tests/mcp/test_supermarket_mcp_contract.py`

**Interfaces:**
- Produces: `ProductPriceResponse.package_size: float`, `.package_unit: str` — consumed by Task 3's `build_retailer_cart.py`.

- [ ] **Step 1: Read the existing contract test file to match its fixture/style**

Run: `cat tests/mcp/test_supermarket_mcp_contract.py` — find the existing `get_product_price` test(s) and the fixture/session setup they use (a seeded `RetailerProduct` row) to match exactly when adding the new assertion.

- [ ] **Step 2: Write the failing test**

Add a new assertion to the existing `get_product_price`-related test (extend it in place rather than duplicating the whole setup) asserting the new fields on the returned structured result, e.g. (adapt to the exact fixture values already used in that test):

```python
    assert structured["package_size"] == <the seeded row's package_size>
    assert structured["package_unit"] == "<the seeded row's package_unit>"
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/mcp/test_supermarket_mcp_contract.py -v`
Expected: FAIL — `KeyError: 'package_size'`.

- [ ] **Step 4: Update `mcp_servers/supermarket_mcp/schemas.py`**

```python
class ProductPriceResponse(BaseModel):
    retailer: str
    store_id: str
    item_code: str
    name: str
    price: float
    unit_price: float
    package_size: float
    package_unit: str
    listed_in_feed: bool
    last_updated_at: str
    stale: bool
```

- [ ] **Step 5: Update `mcp_servers/supermarket_mcp/server.py`**

In `get_product_price`, add the two fields to the `ProductPriceResponse(...)` construction:

```python
        return ProductPriceResponse(
            retailer=product.retailer,
            store_id=product.store_id,
            item_code=product.item_code,
            name=product.name,
            price=product.price,
            unit_price=unit_price(product.price, product.package_size, product.package_unit),
            package_size=product.package_size,
            package_unit=product.package_unit,
            listed_in_feed=product.listed_in_feed,
            last_updated_at=product.last_updated_at.isoformat(),
            stale=status.stale if status else False,
        )
```

- [ ] **Step 6: Run to verify it passes**

Run: `python -m pytest tests/mcp/test_supermarket_mcp_contract.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add mcp_servers/supermarket_mcp/schemas.py mcp_servers/supermarket_mcp/server.py tests/mcp/test_supermarket_mcp_contract.py
git commit -m "feat(supermarket-mcp): expose package_size/package_unit on get_product_price"
```

---

### Task 3: Thread `package_size`/`package_unit` through the agent's cart line and MCP payload

**Files:**
- Modify: `app/agent/nodes/build_retailer_cart.py`
- Modify: `app/agent/nodes/prepare_retailer_cart.py`
- Test: Modify `tests/agent/test_recipe_quantity_propagation.py`
- Test: Modify `tests/agent/test_budget_constrained_selection.py` (fixture prices dicts need the two new keys — see Step 5)

**Interfaces:**
- Consumes: `price_info["package_size"]`/`["package_unit"]` (Task 2).
- Produces: cart line `["package_size"]`/`["package_unit"]`, and the item dict sent to `retailer_cart_client.prepare_retailer_cart` gains `"package_size"`/`"package_unit"` keys — consumed by Task 4/5.

- [ ] **Step 1: Write the failing test**

Add to `tests/agent/test_recipe_quantity_propagation.py`, after `test_prepare_retailer_cart_payload_uses_the_normalized_quantity_not_qty_1`:

```python
async def test_prepare_retailer_cart_payload_includes_the_matched_products_package_size():
    # Regression guard for the whole-package quantity fix: the Retailer-Cart MCP needs
    # to know the matched product's own package size to know how many whole packages
    # to buy when a weight/volume amount was requested against a whole-package product.
    llm = FakeLLM(ParsedRequestSchema(request_type="recipe", recipe_query="tuna pasta", servings=4, items=[]))
    recipe_client = FakeRecipeClient(
        search_results={"tuna pasta": [{"id": 10, "title": "Tuna Pasta"}]},
        recipes={10: {"title": "Tuna Pasta", "servings": 4, "ingredients": [
            {"name": "pasta", "amount": 1000.0, "unit": "g"},
        ]}},
    )
    candidates = {
        ("פסטה", "shufersal"): [{"item_code": "S-PASTA", "name": "Pasta Fusilli 500g", "price": 8.9}],
        ("Pasta Fusilli 500g", "shufersal"): [{"item_code": "S-PASTA", "name": "Pasta Fusilli 500g", "price": 8.9}],
        ("פסטה", "rami_levy"): [{"item_code": "R-PASTA", "name": "Pasta Fusilli 500g", "price": 7.9}],
        ("Pasta Fusilli 500g", "rami_levy"): [{"item_code": "R-PASTA", "name": "Pasta Fusilli 500g", "price": 7.9}],
    }
    prices = {
        ("shufersal", "S-PASTA"): {"unit_price": 0.0178, "price": 8.9, "package_size": 500.0, "package_unit": "g"},
        ("rami_levy", "R-PASTA"): {"unit_price": 0.0158, "price": 7.9, "package_size": 500.0, "package_unit": "g"},
    }
    retailer_cart_client = FakeRetailerCartClient({"retailer": "shufersal", "added": [], "failed": [],
                                                    "blocked": False, "blocked_reason": None, "cart_url": None})
    app = build_graph(
        FakeSupermarketDataClient(candidates, prices), llm, MemorySaver(),
        recipe_client=recipe_client, retailer_cart_client=retailer_cart_client,
        ingredient_dictionary={"pasta": "פסטה"},
    )
    config = {"configurable": {"thread_id": "pasta1"}}

    await app.ainvoke({"raw_message": "tuna pasta"}, config=config)
    await app.ainvoke(Command(resume=["pasta"]), config=config)
    await app.ainvoke(Command(resume="shufersal"), config=config)

    _, called_items = retailer_cart_client.calls[0]
    pasta_call = called_items[0]
    assert pasta_call["quantity"] == 1000.0
    assert pasta_call["unit"] == "g"
    assert pasta_call["package_size"] == 500.0
    assert pasta_call["package_unit"] == "g"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/agent/test_recipe_quantity_propagation.py -v -k package_size`
Expected: FAIL — `KeyError: 'package_size'` on `pasta_call`.

- [ ] **Step 3: Update `app/agent/nodes/build_retailer_cart.py`**

`FakeSupermarketDataClient.get_product_price` (a test double) already just returns whatever dict it's given, so no fake changes are needed beyond the test's own `prices` dict above. In `_add_every_item` and `_select_items_within_budget`, add `package_size`/`package_unit` to each appended line dict (both functions build a line dict with the same core fields — update both for consistency):

In `_add_every_item`, the `lines.append({...})` call becomes:

```python
        lines.append({
            "name": name,
            "item_code": best["item_code"],
            "product_name": best["name"],
            "unit_price": price_info["unit_price"],
            "qty": 1,
            "requested_quantity": item.get("quantity"),
            "requested_unit": item.get("unit") if item.get("quantity") is not None else None,
            "subtotal": price_info["price"],
            "package_size": price_info.get("package_size"),
            "package_unit": price_info.get("package_unit"),
        })
```

In `_select_items_within_budget`, the `lines.append({...})` call becomes:

```python
        lines.append({
            "name": name,
            "item_code": best["item_code"],
            "product_name": best["name"],
            "unit_price": price_info["unit_price"],
            "qty": 1,
            "requested_quantity": item.get("quantity"),
            "requested_unit": item.get("unit") if item.get("quantity") is not None else None,
            "subtotal": cost,
            "package_size": price_info.get("package_size"),
            "package_unit": price_info.get("package_unit"),
        })
```

Using `.get(...)` (not `[...]`) on `price_info` keeps this backward compatible with any test double that doesn't supply these keys (they'll simply be `None`).

- [ ] **Step 4: Update `app/agent/nodes/prepare_retailer_cart.py`**

```python
        items = [
            {
                "name": line["name"],
                "item_code": line["item_code"],
                "quantity": line["requested_quantity"] if line.get("requested_quantity") is not None else line["qty"],
                "unit": line.get("requested_unit"),
                "package_size": line.get("package_size"),
                "package_unit": line.get("package_unit"),
            }
            for line in cart["items"]
        ]
```

- [ ] **Step 5: Run to verify it passes, then run the full agent suite**

Run: `python -m pytest tests/agent/test_recipe_quantity_propagation.py -v`
Expected: all PASS.

Run: `python -m pytest tests/agent -v 2>&1 | tail -40`
Expected: all PASS. If `tests/agent/test_budget_constrained_selection.py`'s `_flat_price_candidates` helper (or any other agent test asserting an exact `called_items` list, e.g. `test_grocery_list_items_still_send_quantity_1_unit_none_no_regression`) fails because it now expects an *exact* dict without the two new keys, fix that assertion the same way `test_weekly_shop_profile_items_send_their_real_per_profile_quantities` already does (assert on the specific fields that matter, e.g. `by_name[...]["quantity"]`/`["unit"]`, rather than an exact full-dict equality) — do not weaken the new package_size/package_unit behavior to make an old exact-equality assertion pass.

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add app/agent/nodes/build_retailer_cart.py app/agent/nodes/prepare_retailer_cart.py tests/agent/test_recipe_quantity_propagation.py
# plus any test file fixed in Step 5
git commit -m "feat(agent): thread matched product's package_size/package_unit into the Retailer-Cart MCP payload"
```

---

### Task 4: `CartItemRequest`/`CartItemResult` schema + `automation.py` plumbing

**Files:**
- Modify: `mcp_servers/retailer_cart_mcp/schemas.py`
- Modify: `mcp_servers/retailer_cart_mcp/automation.py`
- Modify: `mcp_servers/retailer_cart_mcp/adapters/shufersal.py` (protocol call site only — see Task 5 for the actual branching logic change)
- Modify: `mcp_servers/retailer_cart_mcp/adapters/rami_levy.py` (protocol call site only — see Task 5)

**Interfaces:**
- Produces: `CartItemRequest.package_size: float | None = None`, `.package_unit: str | None = None`. `RetailerAdapter.add_to_cart(..., package_size: float | None = None, package_unit: str | None = None)`.

- [ ] **Step 1: Update `mcp_servers/retailer_cart_mcp/schemas.py`**

```python
class CartItemRequest(BaseModel):
    name: str
    item_code: str
    quantity: float
    # None (the default) means "no recipe-derived amount — legacy whole-unit request",
    # and adapters must behave exactly as before this field existed. Any other value
    # ("g", "kg", "unit", "large", ...) means `quantity` is a recipe's actual requested
    # amount in that unit, and adapters run it through the retailer-specific quantity
    # conversion in mcp_servers/retailer_cart_mcp/quantity.py instead.
    unit: str | None = None
    # The matched product's own package size/unit from the local catalog (e.g. 500 "g"
    # for a pasta box) -- None when unknown. Only meaningful together with `unit` being
    # a real weight/volume: lets an adapter buy enough whole packages to cover a
    # requested weight/volume instead of always assuming one package is enough (see
    # quantity.py's packages_needed).
    package_size: float | None = None
    package_unit: str | None = None
```

- [ ] **Step 2: Update `mcp_servers/retailer_cart_mcp/automation.py`**

In `prepare_cart_for_retailer`'s item loop, change:

```python
                    name, item_code, quantity = item["name"], item["item_code"], item["quantity"]
                    unit = item.get("unit")  # None => legacy request, unchanged behavior below
```

to:

```python
                    name, item_code, quantity = item["name"], item["item_code"], item["quantity"]
                    unit = item.get("unit")  # None => legacy request, unchanged behavior below
                    package_size = item.get("package_size")
                    package_unit = item.get("package_unit")
```

And change the `add_to_cart` call:

```python
                        try:
                            result = await adapter.add_to_cart(
                                item_page, match, quantity, unit,
                                package_size=package_size, package_unit=package_unit,
                            )
```

- [ ] **Step 3: Update the `RetailerAdapter` protocol's `add_to_cart` signature in `automation.py`**

```python
    async def add_to_cart(
        self, page: Page, match: MatchResult, quantity: float, unit: str | None = None,
        *, package_size: float | None = None, package_unit: str | None = None,
    ) -> AddToCartResult:
        """Adds the matched product to the cart and returns what actually ended up
        there. `unit=None` (the default) means a legacy whole-unit request — behavior
        must be unchanged from before `unit` existed. Any other `unit` (e.g. "g", "kg",
        "large") means `quantity` is a recipe's real requested amount in that unit;
        adapters run it through mcp_servers/retailer_cart_mcp/quantity.py's conversion
        helpers to decide what to actually add. `package_size`/`package_unit`, when
        given, are the matched product's own known package size from the local catalog
        — used only when `unit` is a weight/volume that doesn't match this product's
        selling method, to buy enough whole packages instead of assuming one is enough
        (see quantity.py's packages_needed). Raises UnsupportedQuantityError or
        QuantityNotConfirmedError for the legacy failure cases, or
        QuantityConversionRequiredError when `unit` and the matched product's retailer
        selling method are incompatible with no deterministic conversion between them.
        """
        ...
```

- [ ] **Step 4: Update both adapters' `add_to_cart` signatures to accept (and, for now, just accept) the new keyword-only params**

In `mcp_servers/retailer_cart_mcp/adapters/shufersal.py`:

```python
    async def add_to_cart(
        self, page: Page, match: MatchResult, quantity: float, unit: str | None = None,
        *, package_size: float | None = None, package_unit: str | None = None,
    ) -> AddToCartResult:
```

In `mcp_servers/retailer_cart_mcp/adapters/rami_levy.py`:

```python
    async def add_to_cart(
        self, page: Page, match: MatchResult, quantity: float, unit: str | None = None,
        *, package_size: float | None = None, package_unit: str | None = None,
    ) -> AddToCartResult:
```

(The actual use of these two new parameters is Task 5 — this task only wires the plumbing through so nothing breaks and the parameters reach the adapters.)

- [ ] **Step 5: Run the full test suite to confirm no regressions from the signature change alone**

Run: `python -m pytest`
Expected: all PASS — every existing call site either doesn't pass these kwargs (they default to `None`) or (Task 3's test) passes them and they're currently just accepted and unused.

- [ ] **Step 6: Commit**

```bash
git add mcp_servers/retailer_cart_mcp/schemas.py mcp_servers/retailer_cart_mcp/automation.py mcp_servers/retailer_cart_mcp/adapters/shufersal.py mcp_servers/retailer_cart_mcp/adapters/rami_levy.py
git commit -m "feat(retailer-cart-mcp): plumb package_size/package_unit through to both adapters"
```

---

### Task 5: Use `packages_needed` in both adapters' whole-package branch

**Files:**
- Modify: `mcp_servers/retailer_cart_mcp/adapters/shufersal.py`
- Modify: `mcp_servers/retailer_cart_mcp/adapters/rami_levy.py`
- Test: Modify `tests/mcp/test_shufersal_adapter.py`
- Test: Modify `tests/mcp/test_rami_levy_adapter.py`

**Interfaces:**
- Consumes: `packages_needed` (Task 1), `package_size`/`package_unit` params (Task 4).

- [ ] **Step 1: Write the failing tests**

Add to `tests/mcp/test_rami_levy_adapter.py`, after `test_whole_unit_item_with_weight_unit_buys_one_whole_package`:

```python
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
```

(These use `FakeTile(is_weighed=False)`, the existing whole-unit fake — check `_match`/`FakeTile`/`FakePage` are already imported/defined earlier in this file; no new fixtures needed.)

Add to `tests/mcp/test_shufersal_adapter.py`, after `test_by_unit_product_with_weight_unit_buys_one_whole_package` (using this file's real existing helpers `FakePage(search_results=[_ok([...])])` and `_by_unit_match()`, confirmed by reading the file directly):

```python
async def test_by_unit_product_with_weight_unit_buys_enough_whole_packages_when_size_known():
    # "1000 g pasta" matched to a 500 g package -> buy 2, not 1 (a real reported bug).
    page = FakePage(search_results=[_ok([
        {"code": "P1", "name": "Pasta", "cartStatus": {"inCart": True, "qty": 2}},
    ])])

    result = await ShufersalAdapter().add_to_cart(
        page, _by_unit_match(), 1000, "g", package_size=500.0, package_unit="g"
    )

    assert result.quantity == 2
    assert result.unit == "unit"
    assert page.add_calls == [{"productCode": "P1", "sellingMethod": "BY_UNIT", "qty": 2}]


async def test_by_unit_product_with_weight_unit_still_buys_one_when_size_unknown():
    page = FakePage(search_results=[_ok([
        {"code": "P1", "name": "Pasta", "cartStatus": {"inCart": True, "qty": 1}},
    ])])

    result = await ShufersalAdapter().add_to_cart(page, _by_unit_match(), 1000, "g")

    assert result.quantity == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/mcp/test_rami_levy_adapter.py tests/mcp/test_shufersal_adapter.py -v -k "packages or package_size or enough_whole or size_known or size_unknown or not_comparable"`
Expected: FAIL — `result.quantity == pytest.approx(1.0)` (still buying only 1) where 2.0 is expected.

- [ ] **Step 3: Update `mcp_servers/retailer_cart_mcp/adapters/rami_levy.py`**

In `add_to_cart`, replace:

```python
        if unit is not None and not is_count_unit(unit):
            # Recipe gave a weight/volume for a product this retailer sells as a whole
            # package/unit (e.g. "250 g pasta" -> one box of pasta) — buy one of it, the
            # ordinary way people shop for packaged goods, same default as Shufersal's
            # equivalent case, rather than inventing a package count from an amount with
            # no per-product package size available to convert with.
            unit_count = 1
```

with:

```python
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
```

Add `packages_needed` to the existing `from mcp_servers.retailer_cart_mcp.quantity import (...)` block at the top of the file.

- [ ] **Step 4: Update `mcp_servers/retailer_cart_mcp/adapters/shufersal.py`**

In `add_to_cart`, replace:

```python
        else:
            # Recipe gave a weight/volume for a product this retailer sells as a whole
            # package/unit (e.g. "250 g pasta" -> one box of pasta) — buy one of it, the
            # ordinary way people shop for packaged goods, rather than inventing a
            # package count from an amount with no known per-product size available to
            # convert with.
            send_qty, result_unit = 1, "unit"
```

with:

```python
        else:
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
            send_qty, result_unit = (count or 1), "unit"
```

Add `packages_needed` to the existing `from mcp_servers.retailer_cart_mcp.quantity import (...)` block at the top of the file.

- [ ] **Step 5: Run to verify the new tests pass**

Run: `python -m pytest tests/mcp/test_rami_levy_adapter.py tests/mcp/test_shufersal_adapter.py -v`
Expected: all PASS, including every pre-existing test in both files (the "buy 1" default is unchanged whenever `package_size`/`package_unit` are absent, which is every pre-existing test's call signature).

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add mcp_servers/retailer_cart_mcp/adapters/shufersal.py mcp_servers/retailer_cart_mcp/adapters/rami_levy.py tests/mcp/test_shufersal_adapter.py tests/mcp/test_rami_levy_adapter.py
git commit -m "fix(retailer-cart-mcp): buy enough whole packages to cover a requested weight/volume, not just one"
```

---

### Task 6: Full verification + live manual re-check

**Files:** none (verification only)

- [ ] **Step 1: Full backend suite**

Run: `make test`
Expected: all PASS.

- [ ] **Step 2: Lint**

Run: `make lint`
Expected: clean.

- [ ] **Step 3: Coverage**

Run: `make coverage`
Expected: clean; `mcp_servers/retailer_cart_mcp/quantity.py`, `mcp_servers/supermarket_mcp/server.py`, `app/agent/nodes/build_retailer_cart.py`, `app/agent/nodes/prepare_retailer_cart.py` all at or near 100%.

- [ ] **Step 4: Frontend build gate**

Run: `cd web && npm run build`
Expected: clean, unchanged (no frontend files touched — `RetailerCartResultView.tsx` already renders `cart_quantity`/`cart_unit` generically, so "Added to cart: 2 unit" displays correctly with zero frontend code changes).

- [ ] **Step 5: Manual verification against the real Docker Compose stack**

Since this fix's core value is only observable end-to-end (correct package math against real local-catalog data + a real add-to-cart confirmation), and the previous two recipe-quantity features in this session were manually verified live:

```bash
docker compose up -d --build supermarket-mcp retailer-cart-mcp backend
```

Re-run the exact reported scenario ("miso cream pasta for 4 servings" -> select pasta -> choose Rami Levy) via `curl -s -X POST http://localhost:8000/chat ...` (see prior manual-verification commands in this session for the exact JSON payload shape) and confirm the final `retailer_cart_result` (or the `RetailerCartResultView` equivalent) shows `cart_quantity` >= 2 (enough 500 g packages to cover 1000 g) for pasta, not 1. Record the actual observed values for the final report. Real add-to-cart against Rami Levy requires a captured login session (`sessions/rami_levy.json`) — if none exists, the response will be `blocked_reason: "login_required"` before ever reaching the quantity logic; in that case, confirm correctness via the automated adapter tests (Task 5) instead and note in the report that live add-to-cart itself couldn't be exercised for that reason.

---

## Self-Review Notes (for the plan author, not a task)

- Spec coverage: "buy enough whole packages instead of just one" is the entire ask — covered end-to-end (Task 1 pure math, Task 2 exposes the local catalog's known package size, Task 3 threads it through the agent's cart line and MCP payload, Task 4 plumbs it through the MCP schema/automation/adapter signatures, Task 5 actually uses it in both adapters' decision logic, Task 6 verifies).
- No placeholders: every step has real, complete code, using each test file's actual existing helpers (`FakePage(search_results=[_ok([...])])`/`_by_unit_match()` for Shufersal, `FakeTile`/`FakePage`/`_match()` for Rami Levy), confirmed by reading both files directly while writing this plan.
- Type consistency: `packages_needed`'s signature is identical everywhere it's referenced (Task 1 defines it, Task 5 calls it in both adapters). `package_size`/`package_unit` names are consistent across every layer (supermarket_mcp's `ProductPriceResponse`, the agent cart line, `CartItemRequest`, `automation.py`, both adapters' `add_to_cart`).
