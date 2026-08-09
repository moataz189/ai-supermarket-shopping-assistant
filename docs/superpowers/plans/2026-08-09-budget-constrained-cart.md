# Budget-Constrained Cart Building Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For open-ended/weekly-profile budget requests, progressively select products so the final cart total never exceeds `budget * 1.10`, while explicit shopping-list requests keep every requested item and only report over-budget trade-offs.

**Architecture:** The LangGraph agent already forks grocery-list requests into two routes at `route_after_parse` (`app/agent/graph.py:24-33`): no items + budget → `resolve_weekly_shop_profile` (asks which starter list, or a custom freeform list) → `resolve_items`; items present → straight to `resolve_items`. Both routes converge on `make_build_retailer_cart` (`app/agent/nodes/build_retailer_cart.py`), which today adds every parsed item regardless of budget and only checks the total afterwards. This plan adds a new `AgentState["open_ended_budget_selection"]` boolean flag, set only by `resolve_weekly_shop_profile`, and branches `build_retailer_cart` on it: when true, a new progressive/greedy selection loop skips any candidate that would push the running total past `allowed_max = round(budget * 1.10, 2)`, in the item list's existing stable order (STARTER_LISTS is already curated "useful items first"); when false (explicit lists, recipes), the existing "add everything" loop is untouched. `finalize.py`'s warning logic is tightened to only raise a hard `budget_exceeded` warning when a cart's total truly exceeds `allowed_max` (not just `budget`), and a new `no_items_within_budget` warning/flag prevents an empty budget-only cart from ever reading as "success".

**Tech Stack:** Python 3 / FastAPI / LangGraph / SQLAlchemy backend (`app/`, `mcp_servers/`), pytest (`asyncio_mode = auto`), React/TypeScript/Vite frontend (`web/`), ruff lint, Docker Compose.

## Global Constraints

- `allowed_max = round(budget * 1.10, 2)` — the only ceiling; never intentionally exceeded by the open-ended/profile selection algorithm.
- Selection must be deterministic (no randomness) — item order comes straight from `parsed_request["items"]`, which is itself deterministic (STARTER_LISTS order, or the user's own typed order for a custom/explicit list).
- Explicit shopping lists (items present in the user's own message) NEVER get items silently dropped for budget reasons — only the open-ended/weekly-profile path (routed via `resolve_weekly_shop_profile`) uses skip-to-fit-budget logic.
- Do not change `qty`/`subtotal` semantics for the existing "add everything" branch (explicit lists, recipes) — that behavior (`qty` always 1, `subtotal` = package price regardless of requested quantity) is a documented, intentional, out-of-scope decision from a prior feature (`build_retailer_cart.py:60-70`) and multiple existing tests depend on it.
- `ruff check app tests mcp_servers` (line-length 100) and `pytest` (via `make lint` / `make test` / `make coverage`) must stay green; `cd web && npm run build` (`tsc -b && vite build`) must stay green.
- Do not make unrelated changes; do not touch Git worktrees.

---

### Task 1: `AgentState` budget-selection flag + weekly-profile flow marks it

**Files:**
- Modify: `app/agent/state.py:48-78` (AgentState)
- Modify: `app/agent/nodes/resolve_weekly_shop_profile.py:119-154` (`resolve_weekly_shop_profile`)
- Test: `tests/agent/test_graph_weekly_shop_profile.py` (extend one existing test)

**Interfaces:**
- Produces: `AgentState["open_ended_budget_selection"]: bool` — read by Task 2's `build_retailer_cart` to choose which selection algorithm to run. Absent (falsy via `state.get(..., False)`) for every request that never goes through `resolve_weekly_shop_profile` (i.e., every explicit shopping list, with or without a budget, and every recipe request).

- [ ] **Step 1: Add the new state field**

In `app/agent/state.py`, add one line inside `AgentState` (after `retailer_carts`, e.g. line 72-73):

```python
    retailer_carts: dict[str, dict]           # "shufersal"/"rami_levy" -> cart dict
    open_ended_budget_selection: bool         # True only when items came from
    # resolve_weekly_shop_profile.py (a budget-only request with no items, or its
    # "custom" freeform follow-up) — tells build_retailer_cart.py to progressively
    # select items that fit `budget * 1.10` instead of adding every item unconditionally.
    # Absent/False for every explicit shopping list (recipe or grocery-list-with-items),
    # which must never have requested items silently dropped for budget reasons.
    chosen_retailer: str | None
```

- [ ] **Step 2: Write the failing test — profile flow sets the flag**

Append to `tests/agent/test_graph_weekly_shop_profile.py`:

```python
async def test_choosing_a_profile_marks_open_ended_budget_selection():
    llm = FakeLLM(ParsedRequestSchema(items=[], budget=250))
    client = FakeSupermarketDataClient({}, {})
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t2e"}}

    await app.ainvoke({"raw_message": "Weekly shopping under ₪250"}, config=config)
    result = await app.ainvoke(Command(resume="basic"), config=config)

    assert result["open_ended_budget_selection"] is True
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd /Users/moatazodeh/Documents/ai-supermarket-agent && python -m pytest tests/agent/test_graph_weekly_shop_profile.py::test_choosing_a_profile_marks_open_ended_budget_selection -v`
Expected: FAIL (KeyError on `result["open_ended_budget_selection"]`, since the node doesn't return it yet).

- [ ] **Step 4: Make `resolve_weekly_shop_profile` return the flag**

In `app/agent/nodes/resolve_weekly_shop_profile.py`, change the final return (currently `return {"parsed_request": parsed}` at line 154):

```python
    parsed = dict(state["parsed_request"])
    parsed["items"] = items
    return {"parsed_request": parsed, "open_ended_budget_selection": True}
```

- [ ] **Step 5: Run the test again to verify it passes**

Run: `python -m pytest tests/agent/test_graph_weekly_shop_profile.py -v`
Expected: all tests in this file PASS (including the new one).

- [ ] **Step 6: Commit**

```bash
git add app/agent/state.py app/agent/nodes/resolve_weekly_shop_profile.py tests/agent/test_graph_weekly_shop_profile.py
git commit -m "feat(agent): mark weekly-profile/open-ended requests for budget-constrained selection"
```

---

### Task 2: Progressive budget-constrained selection in `build_retailer_cart`

**Files:**
- Modify: `app/agent/nodes/build_retailer_cart.py` (full rewrite of `build_cart`'s body, new helpers)
- Test: Create `tests/agent/test_budget_constrained_selection.py`

**Interfaces:**
- Consumes: `AgentState["open_ended_budget_selection"]` (Task 1). `parsed_request["budget"]: float | None` (existing). `SupermarketDataClient.search_product(query, retailer) -> list[dict]` / `.get_product_price(retailer, item_code) -> dict | None` (existing, `app/agent/mcp_clients.py:7-9`) — each price dict has `"price"` (package price) and `"unit_price"` (price per gram/ml/package-unit, see `app/db/repositories.py:9-11`).
- Produces: every `retailer_carts[retailer]` dict now always has two new keys: `"allowed_max": float | None` (`round(budget * 1.10, 2)` when budget is set, else `None`) and `"no_items_fit_budget": bool` (True only when the open-ended branch ran and ended with zero cart lines). Consumed by Task 4 (`finalize.py`) and Task 6 (API schema/frontend).

- [ ] **Step 1: Write the failing tests**

Create `tests/agent/test_budget_constrained_selection.py`:

```python
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from app.agent.nodes.resolve_weekly_shop_profile import STARTER_LISTS
from tests.agent.fakes import FakeLLM, FakeSupermarketDataClient


def _flat_price_candidates(names_and_prices: dict[str, dict[str, float]]) -> tuple[dict, dict]:
    """Builds FakeSupermarketDataClient candidates/prices where a product's own `name`
    equals the search query it's found under, for both retailers, so build_retailer_cart's
    second (resolved-label) search hits the same fixture entry as resolve_items' first
    search — avoids needing two near-duplicate fixture rows per item like other tests do.
    `names_and_prices` maps item name -> {"shufersal": price, "rami_levy": price}.
    """
    candidates: dict[tuple[str, str], list[dict]] = {}
    prices: dict[tuple[str, str], dict] = {}
    for i, (name, per_retailer) in enumerate(names_and_prices.items()):
        for retailer, price in per_retailer.items():
            item_code = f"{retailer[:1].upper()}-{i}"
            candidates[(name, retailer)] = [{"item_code": item_code, "name": name, "price": price}]
            prices[(retailer, item_code)] = {"unit_price": price, "price": price}
    return candidates, prices


async def _run_basic_profile(budget, names_and_prices, thread_id):
    llm = FakeLLM(ParsedRequestSchema(items=[], budget=budget))
    candidates, prices = _flat_price_candidates(names_and_prices)
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": thread_id}}
    await app.ainvoke({"raw_message": "groceries"}, config=config)
    return await app.ainvoke(Command(resume="basic"), config=config)


# Only the plain unit-count items from "basic" (not the two kg-priced items,
# "עגבניה"/"בצל") — _estimated_cost treats "kg" specially (unit_price x grams), so a
# flat per-item price only maps directly to cost for quantity=1/unit="unit" items; the
# dedicated weighted-item test below covers the "kg" branch on its own.
UNIT_ITEM_NAMES = [
    entry["name"] for entry in STARTER_LISTS["basic"] if entry["unit"] == "unit"
]  # 6 items: לחם, חלב, ביצים, אורז, פסטה, שמן זית — every one at quantity=1


async def test_budget_20_never_exceeds_22():
    prices = {name: {"shufersal": 6.0, "rami_levy": 6.0} for name in UNIT_ITEM_NAMES}
    result = await _run_basic_profile(20, prices, "b20")
    carts = result["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["total"] <= 22.0
    assert carts["rami_levy"]["total"] <= 22.0
    assert carts["shufersal"]["allowed_max"] == 22.0


async def test_budget_100_never_exceeds_110():
    prices = {name: {"shufersal": 14.0, "rami_levy": 14.0} for name in UNIT_ITEM_NAMES}
    result = await _run_basic_profile(100, prices, "b100")
    carts = result["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["total"] <= 110.0
    assert carts["rami_levy"]["total"] <= 110.0


async def test_total_slightly_above_budget_but_within_tolerance_is_accepted():
    # 4 items @ 25.5 = 102.0 -> over the ₪100 budget but under the ₪110 allowed_max.
    # The other 2 basic unit-items are deliberately left unstubbed (no candidates at
    # all -> reported missing, not zero-priced -- a zero price would trivially "fit"
    # and could mask a bug in the cap logic).
    prices = {name: {"shufersal": 25.5, "rami_levy": 25.5} for name in UNIT_ITEM_NAMES[:4]}
    result = await _run_basic_profile(100, prices, "btol")
    carts = result["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["total"] == 102.0
    assert carts["shufersal"]["over_budget_by"] == 2.0
    assert carts["shufersal"]["allowed_max"] == 110.0
    assert carts["shufersal"]["no_items_fit_budget"] is False


async def test_cart_above_tolerance_is_never_constructed():
    # Every candidate costs more than allowed_max (₪22) on its own -> none can be added.
    prices = {name: {"shufersal": 30.0, "rami_levy": 30.0} for name in UNIT_ITEM_NAMES}
    result = await _run_basic_profile(20, prices, "babove")
    carts = result["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["items"] == []
    assert carts["shufersal"]["total"] == 0


async def test_algorithm_gets_reasonably_close_to_target_budget():
    # 6 items @ 25 = 150, but only 4 fit under allowed_max (110) before the 5th would
    # overshoot -> total lands exactly on budget, not far below it.
    prices = {name: {"shufersal": 25.0, "rami_levy": 25.0} for name in UNIT_ITEM_NAMES}
    result = await _run_basic_profile(100, prices, "bclose")
    carts = result["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["total"] == 100.0
    assert carts["shufersal"]["total"] >= 100 * 0.8


async def test_selection_is_deterministic_across_repeated_runs():
    prices = {name: {"shufersal": 9.0, "rami_levy": 9.0} for name in UNIT_ITEM_NAMES}
    first = await _run_basic_profile(30, prices, "bdet1")
    second = await _run_basic_profile(30, prices, "bdet2")
    first_items = [i["item_code"] for i in first["__interrupt__"][0].value["carts"]["shufersal"]["items"]]
    second_items = [i["item_code"] for i in second["__interrupt__"][0].value["carts"]["shufersal"]["items"]]
    assert first_items == second_items
    assert first["__interrupt__"][0].value["carts"]["shufersal"]["total"] == \
        second["__interrupt__"][0].value["carts"]["shufersal"]["total"]


async def test_shufersal_and_rami_levy_respect_budget_independently():
    # Rami Levy is cheaper across the board -> it should fit more items than Shufersal
    # while both stay within their own ₪55 allowed_max, independently.
    prices = {name: {"shufersal": 14.0, "rami_levy": 9.0} for name in UNIT_ITEM_NAMES}
    result = await _run_basic_profile(50, prices, "bretailer")
    carts = result["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["total"] <= 55.0
    assert carts["rami_levy"]["total"] <= 55.0
    assert len(carts["rami_levy"]["items"]) > len(carts["shufersal"]["items"])


async def test_weighted_item_quantity_used_for_budget_math():
    # "one_person" starter list includes "חזה עוף" (chicken breast) at 0.4 kg.
    llm = FakeLLM(ParsedRequestSchema(items=[], budget=100))
    candidates = {
        ("חזה עוף", "shufersal"): [{"item_code": "S-CHKN", "name": "חזה עוף", "price": 20.0}],
        ("חזה עוף", "rami_levy"): [{"item_code": "R-CHKN", "name": "חזה עוף", "price": 20.0}],
    }
    prices = {
        # unit_price is price per GRAM (see app/db/repositories.py's unit_price) -- 0.02
        # ₪/g == ₪20/kg, matching what a real weighted-product feed row would compute to.
        # `price` (₪20.0) is the raw package-row price, unused by the "kg" cost branch.
        ("shufersal", "S-CHKN"): {"unit_price": 0.02, "price": 20.0},
        ("rami_levy", "R-CHKN"): {"unit_price": 0.02, "price": 20.0},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "bweighted"}}
    await app.ainvoke({"raw_message": "groceries"}, config=config)
    result = await app.ainvoke(Command(resume="one_person"), config=config)

    cart = result["__interrupt__"][0].value["carts"]["shufersal"]
    chicken = next(i for i in cart["items"] if i["name"] == "חזה עוף")
    # 0.4 kg at ₪20/kg (unit_price 0.02 ₪/g) -> 0.02 * 0.4 * 1000 = ₪8.00, NOT the raw
    # ₪20.0 package price a qty=1 assumption would have used.
    assert chicken["subtotal"] == 8.0
    assert cart["total"] == 8.0


async def test_explicit_shopping_list_with_budget_keeps_every_requested_item():
    llm = FakeLLM(ParsedRequestSchema(items=["milk", "eggs", "bread", "chicken"], budget=20))
    candidates = {}
    prices = {}
    for i, (name, price) in enumerate([("milk", 8.0), ("eggs", 8.0), ("bread", 8.0), ("chicken", 8.0)]):
        code = f"S-{i}"
        candidates[(name, "shufersal")] = [{"item_code": code, "name": name, "price": price}]
        candidates[(name, "rami_levy")] = [{"item_code": code, "name": name, "price": price}]
        prices[("shufersal", code)] = {"unit_price": price, "price": price}
        prices[("rami_levy", code)] = {"unit_price": price, "price": price}
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "bexplicit"}}

    result = await app.ainvoke({"raw_message": "milk, eggs, bread and chicken under 20"}, config=config)

    carts = result["__interrupt__"][0].value["carts"]
    shufersal = carts["shufersal"]
    # All 4 requested items are present (added), none silently dropped for budget reasons.
    assert len(shufersal["items"]) == 4
    assert shufersal["total"] == 32.0
    # Explicit lists are allowed to exceed the 10% tolerance -- never budget-limited.
    assert shufersal["total"] > shufersal["allowed_max"]


async def test_no_products_fit_budget_does_not_produce_a_successful_empty_cart():
    prices = {name: {"shufersal": 500.0, "rami_levy": 500.0} for name in UNIT_ITEM_NAMES}
    result = await _run_basic_profile(1, prices, "bempty")
    carts = result["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["items"] == []
    assert carts["shufersal"]["total"] == 0
    assert carts["shufersal"]["no_items_fit_budget"] is True


async def test_non_budget_grocery_list_is_unaffected():
    """Regression guard: a normal explicit list with no budget at all keeps behaving
    exactly as before, and the new fields default to their no-op values."""
    llm = FakeLLM(ParsedRequestSchema(items=["milk"]))
    candidates = {
        ("milk", "shufersal"): [{"item_code": "S-MILK", "name": "Milk 3%", "price": 6.0}],
        ("Milk 3%", "shufersal"): [{"item_code": "S-MILK", "name": "Milk 3%", "price": 6.0}],
        ("milk", "rami_levy"): [{"item_code": "R-MILK", "name": "Milk 3%", "price": 5.5}],
        ("Milk 3%", "rami_levy"): [{"item_code": "R-MILK", "name": "Milk 3%", "price": 5.5}],
    }
    prices = {
        ("shufersal", "S-MILK"): {"unit_price": 6.0, "price": 6.0},
        ("rami_levy", "R-MILK"): {"unit_price": 5.5, "price": 5.5},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "bnobudget"}}

    result = await app.ainvoke({"raw_message": "milk"}, config=config)

    cart = result["__interrupt__"][0].value["carts"]["shufersal"]
    assert cart["total"] == 6.0
    assert cart["allowed_max"] is None
    assert cart["no_items_fit_budget"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/agent/test_budget_constrained_selection.py -v`
Expected: FAIL — `KeyError: 'allowed_max'` (and several totals exceeding the asserted caps), since `build_retailer_cart.py` doesn't produce these fields or behavior yet.

- [ ] **Step 3: Rewrite `app/agent/nodes/build_retailer_cart.py`**

Replace the full file contents:

```python
from app.agent.state import AgentState
from app.dietary.rules import find_substitute_query, forbidden_tags, tags_for_name


async def _suggest_trade_off(client, retailer: str, most_expensive: dict) -> dict | None:
    candidates = await client.search_product(most_expensive["name"], retailer)
    cheaper = [
        c for c in candidates
        if c["item_code"] != most_expensive["item_code"] and c["price"] < most_expensive["subtotal"]
    ]
    if not cheaper:
        return None
    alt = min(cheaper, key=lambda c: c["price"])
    return {
        "item_name": most_expensive["name"],
        "current_choice": most_expensive["product_name"],
        "suggested_choice": alt["name"],
        "savings": round(most_expensive["subtotal"] - alt["price"], 2),
    }


def _label_for(name: str, item: dict, resolved_choices: dict, retailer: str) -> str:
    # Prefer THIS retailer's own resolved catalog product name (resolved_choices is
    # per-retailer, CP9 follow-up, 2026-08-08 — a retailer's real product name for "the
    # same" item can genuinely differ from another retailer's); otherwise fall back to
    # search_name — always tried in Hebrew when a translation exists, regardless of this
    # conversation's own language, since the real catalog is Hebrew-only.
    return (
        resolved_choices.get(name, {}).get(retailer)
        or item.get("search_name")
        or item.get("display_name")
        or name
    )


async def _candidates_for(
    client, retailer: str, name: str, label: str, forbidden: set[str], dietary_conflicts: list[str],
) -> tuple[list[dict], dict | None]:
    """Returns (candidates, missing_entry). `missing_entry` is None when candidates were
    found; otherwise it's the dict to append to this retailer's `missing_items`."""
    candidates = await client.search_product(label, retailer)
    if forbidden:
        compliant = [c for c in candidates if not (tags_for_name(c["name"]) & forbidden)]
        if not compliant:
            sub_query = find_substitute_query(name, forbidden)
            compliant = await client.search_product(sub_query, retailer) if sub_query else []
        candidates = compliant
    if not candidates:
        reason = "dietary_conflict" if name in dietary_conflicts else "not_found"
        return [], {"name": name, "reason": reason}
    return candidates, None


def _estimated_cost(price_info: dict, quantity: float | None, unit: str | None) -> float:
    """Best-effort cost for one cart line honoring the item's real required quantity —
    used only by the open-ended/weekly-profile budget-constrained selection below to
    decide whether a candidate fits the remaining budget. `unit_price` is price per
    gram/ml/package-unit (see app/db/repositories.py's unit_price); "kg" is the only
    weight unit STARTER_LISTS/recipes ever attach to a grocery-list item, so a "kg"
    request is priced via unit_price (price-per-gram) x grams requested. Any other unit
    (or no quantity at all) is priced as a straight package-count multiple of the
    package price, matching how a plain unit count (loaves, cartons...) is actually
    sold."""
    if quantity is None or unit is None:
        return price_info["price"]
    if unit == "kg":
        return round(price_info["unit_price"] * quantity * 1000, 2)
    return round(price_info["price"] * quantity, 2)


async def _add_every_item(
    client, retailer: str, items: list[dict], resolved_choices: dict, forbidden: set[str],
    dietary_conflicts: list[str],
) -> tuple[list[dict], list[dict]]:
    """The pre-existing behavior for explicit shopping lists and recipes: every item is
    resolved and added regardless of budget — the user's explicit intent is never
    silently dropped (budget-constrained selection is reserved for
    open_ended_budget_selection carts, see _select_items_within_budget below)."""
    lines: list[dict] = []
    missing: list[dict] = []
    for item in items:
        name = item["name"]
        label = _label_for(name, item, resolved_choices, retailer)
        candidates, missing_entry = await _candidates_for(
            client, retailer, name, label, forbidden, dietary_conflicts
        )
        if missing_entry is not None:
            missing.append({"name": item.get("display_name") or missing_entry["name"], "reason": missing_entry["reason"]})
            continue

        best = min(candidates, key=lambda c: c["price"])
        price_info = await client.get_product_price(retailer, best["item_code"])
        # `quantity`/`unit` are only ever set on recipe-derived items (CP7's
        # get_recipe_ingredients) — None for ordinary grocery-list items. `qty` here
        # (used only for this retailer's own price-comparison subtotal/total math)
        # intentionally stays 1 regardless — recipe quantities are a real amount to add
        # to the retailer's cart, not a multiplier on the comparison-view price; the
        # retailer cart's actual add-to-cart quantity is requested_quantity/
        # requested_unit below, threaded through prepare_retailer_cart.py.
        lines.append({
            "name": name,
            "item_code": best["item_code"],
            "product_name": best["name"],
            "unit_price": price_info["unit_price"],
            "qty": 1,
            "requested_quantity": item.get("quantity"),
            "requested_unit": item.get("unit") if item.get("quantity") is not None else None,
            "subtotal": price_info["price"],
        })
    return lines, missing


async def _select_items_within_budget(
    client, retailer: str, items: list[dict], resolved_choices: dict, forbidden: set[str],
    dietary_conflicts: list[str], budget: float,
) -> tuple[list[dict], list[dict], float]:
    """Only used for open_ended_budget_selection carts (a budget-only request with no
    items, or its "custom" freeform follow-up — see resolve_weekly_shop_profile.py).
    Walks `items` in their existing stable order (STARTER_LISTS is already curated
    "useful/common items first" with reasonable category spread) and greedily adds each
    item's cheapest matching candidate, using its real required quantity
    (_estimated_cost) — skipping (never adding) any single item whose cost would push
    the running total past `budget * 1.10`, then continuing to try the rest of the list
    rather than stopping outright, so a handful of expensive items don't starve an
    otherwise-affordable cart. Deterministic: no randomness, stable input order, stable
    price-based tie-break per item (cheapest candidate wins, same as the non-budget
    path)."""
    allowed_max = round(budget * 1.10, 2)
    lines: list[dict] = []
    missing: list[dict] = []
    running_total = 0.0

    for item in items:
        name = item["name"]
        label = _label_for(name, item, resolved_choices, retailer)
        candidates, missing_entry = await _candidates_for(
            client, retailer, name, label, forbidden, dietary_conflicts
        )
        if missing_entry is not None:
            missing.append({"name": item.get("display_name") or missing_entry["name"], "reason": missing_entry["reason"]})
            continue

        best = min(candidates, key=lambda c: c["price"])
        price_info = await client.get_product_price(retailer, best["item_code"])
        cost = _estimated_cost(price_info, item.get("quantity"), item.get("unit"))

        if round(running_total + cost, 2) > allowed_max:
            continue  # doesn't fit within the tolerance -- skip it, keep trying the rest

        running_total = round(running_total + cost, 2)
        lines.append({
            "name": name,
            "item_code": best["item_code"],
            "product_name": best["name"],
            "unit_price": price_info["unit_price"],
            "qty": 1,
            "requested_quantity": item.get("quantity"),
            "requested_unit": item.get("unit") if item.get("quantity") is not None else None,
            "subtotal": cost,
        })

    return lines, missing, running_total


def make_build_retailer_cart(retailer: str, client):
    async def build_cart(state: AgentState) -> AgentState:
        parsed = state["parsed_request"]
        forbidden = forbidden_tags(parsed.get("dietary_constraints", []))
        dietary_conflicts = state.get("dietary_conflicts", [])
        resolved_choices = state["resolved_choices"]
        budget = parsed.get("budget")
        open_ended = state.get("open_ended_budget_selection", False)

        trade_offs: list[dict] = []
        no_items_fit_budget = False

        if open_ended and budget is not None:
            lines, missing, total = await _select_items_within_budget(
                client, retailer, parsed["items"], resolved_choices, forbidden, dietary_conflicts, budget,
            )
            no_items_fit_budget = not lines
        else:
            lines, missing = await _add_every_item(
                client, retailer, parsed["items"], resolved_choices, forbidden, dietary_conflicts,
            )
            total = sum(line["subtotal"] for line in lines)

        over_budget_by = round(total - budget, 2) if budget is not None and total > budget else None
        allowed_max = round(budget * 1.10, 2) if budget is not None else None

        if not open_ended and over_budget_by is not None and lines:
            most_expensive = max(lines, key=lambda l: l["subtotal"])
            suggestion = await _suggest_trade_off(client, retailer, most_expensive)
            if suggestion:
                trade_offs.append(suggestion)

        cart = {
            "retailer": retailer,
            "items": lines,
            "missing_items": missing,
            "total": total,
            "budget": budget,
            "allowed_max": allowed_max,
            "over_budget_by": over_budget_by,
            "no_items_fit_budget": no_items_fit_budget,
            "trade_off_suggestions": trade_offs,
        }
        return {"retailer_carts": {**state.get("retailer_carts", {}), retailer: cart}}

    return build_cart
```

Note: `state["resolved_choices"]` (not `.get(...)`) is safe here — `resolve_items` always runs before either `build_shufersal_cart`/`build_rami_levy_cart` (see `app/agent/graph.py:95-99`) and always returns a `resolved_choices` key (possibly `{}`), exactly as the pre-existing code already assumed via `state["resolved_choices"].get(name, {})`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/agent/test_budget_constrained_selection.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full existing agent test suite to check for regressions**

Run: `python -m pytest tests/agent -v`
Expected: all PASS, including `test_budget_trade_off_suggestion.py` and every test in `test_graph_weekly_shop_profile.py` and `test_recipe_quantity_propagation.py`.

- [ ] **Step 6: Commit**

```bash
git add app/agent/nodes/build_retailer_cart.py tests/agent/test_budget_constrained_selection.py
git commit -m "feat(agent): progressively select items to fit a 10%-tolerance budget for open-ended/weekly-profile carts"
```

---

### Task 3: `finalize.py` — tolerance-aware warnings, no empty-success carts

**Files:**
- Modify: `app/agent/nodes/finalize.py`
- Test: Create `tests/agent/test_finalize_budget_warnings.py`

**Interfaces:**
- Consumes: `retailer_carts[retailer]["allowed_max"]` / `["no_items_fit_budget"]` / `["over_budget_by"]` / `["total"]` (Task 2).
- Produces: `warnings` entries `{"code": "budget_exceeded", "retailer": ..., "over_budget_by": ...}` (existing shape, now only emitted when a cart's total truly exceeds `allowed_max`) and a new `{"code": "no_items_within_budget", "retailer": ...}` (emitted whenever `no_items_fit_budget` is True) — consumed by Task 6's `WarningsList.tsx`.

- [ ] **Step 1: Write the failing tests**

Create `tests/agent/test_finalize_budget_warnings.py`:

```python
from app.agent.nodes.finalize import finalize


def _state(cart: dict) -> dict:
    return {
        "retailer_carts": {"shufersal": cart},
        "chosen_retailer": None,
        "retailer_cart_result": None,
    }


def _cart(**overrides) -> dict:
    base = {
        "retailer": "shufersal", "items": [], "missing_items": [], "total": 0.0,
        "budget": None, "allowed_max": None, "over_budget_by": None,
        "no_items_fit_budget": False, "trade_off_suggestions": [],
    }
    base.update(overrides)
    return base


def test_no_warning_when_within_the_10_percent_tolerance():
    cart = _cart(total=102.0, budget=100.0, allowed_max=110.0, over_budget_by=2.0)
    result = finalize(_state(cart))
    codes = {w["code"] for w in result["warnings"]}
    assert "budget_exceeded" not in codes
    assert result["status"] == "success"


def test_warning_when_truly_over_the_10_percent_tolerance():
    cart = _cart(total=115.0, budget=100.0, allowed_max=110.0, over_budget_by=15.0)
    result = finalize(_state(cart))
    warning = next(w for w in result["warnings"] if w["code"] == "budget_exceeded")
    assert warning["retailer"] == "shufersal"
    assert warning["over_budget_by"] == 15.0
    assert result["status"] == "partial_success"


def test_no_items_within_budget_warning_prevents_successful_empty_cart():
    cart = _cart(total=0.0, budget=20.0, allowed_max=22.0, no_items_fit_budget=True)
    result = finalize(_state(cart))
    codes = {w["code"] for w in result["warnings"]}
    assert "no_items_within_budget" in codes
    assert result["status"] == "partial_success"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/agent/test_finalize_budget_warnings.py -v`
Expected: FAIL — `test_no_warning_when_within_the_10_percent_tolerance` and `test_no_items_within_budget_warning_prevents_successful_empty_cart` fail against current `finalize.py`.

- [ ] **Step 3: Update `app/agent/nodes/finalize.py`**

Replace the loop body (currently lines 12-17):

```python
    warnings = []
    for retailer, cart in relevant_carts.items():
        if cart["missing_items"]:
            warnings.append({"code": "product_not_found", "retailer": retailer, "items": cart["missing_items"]})
        if cart["no_items_fit_budget"]:
            warnings.append({"code": "no_items_within_budget", "retailer": retailer})
        elif cart["allowed_max"] is not None and cart["total"] > cart["allowed_max"]:
            warnings.append({"code": "budget_exceeded", "retailer": retailer, "over_budget_by": cart["over_budget_by"]})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/agent/test_finalize_budget_warnings.py tests/agent/test_finalize_warnings.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full agent + api suite**

Run: `python -m pytest tests/agent tests/api -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/agent/nodes/finalize.py tests/agent/test_finalize_budget_warnings.py
git commit -m "fix(agent): only warn budget_exceeded beyond the 10% tolerance; flag empty budget-only carts"
```

---

### Task 4: API schema + TypeScript types for the two new cart fields

**Files:**
- Modify: `app/api/schemas.py:85-92` (`RetailerCart`)
- Modify: `web/src/api.ts:57-66` (`RetailerCart` interface)
- Test: Create `tests/api/test_budget_fields_in_response.py`

**Interfaces:**
- Produces: `RetailerCart.allowed_max: float | None`, `RetailerCart.no_items_fit_budget: bool` on the `/chat` JSON response — consumed by Task 5 (`RetailerCard.tsx`, `WarningsList.tsx`).

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_budget_fields_in_response.py`:

```python
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from app.api.dependencies import get_agent_app
from app.api.main import app
from tests.agent.fakes import FakeLLM, FakeSupermarketDataClient

client = TestClient(app)


def test_chat_response_includes_allowed_max_and_no_items_fit_budget():
    llm = FakeLLM(ParsedRequestSchema(items=["milk"], budget=20))
    candidates = {
        ("milk", "shufersal"): [{"item_code": "S-MILK", "name": "Milk 3%", "price": 6.0}],
        ("Milk 3%", "shufersal"): [{"item_code": "S-MILK", "name": "Milk 3%", "price": 6.0}],
        ("milk", "rami_levy"): [{"item_code": "R-MILK", "name": "Milk 3%", "price": 5.5}],
        ("Milk 3%", "rami_levy"): [{"item_code": "R-MILK", "name": "Milk 3%", "price": 5.5}],
    }
    prices = {
        ("shufersal", "S-MILK"): {"unit_price": 6.0, "price": 6.0},
        ("rami_levy", "R-MILK"): {"unit_price": 5.5, "price": 5.5},
    }
    fake_app = build_graph(FakeSupermarketDataClient(candidates, prices), llm, MemorySaver())
    app.dependency_overrides[get_agent_app] = lambda: fake_app
    try:
        response = client.post("/chat", json={"message": "milk under 20"})
        assert response.status_code == 200
        cart = response.json()["clarification"]["carts"]["shufersal"]
        assert cart["allowed_max"] == 22.0
        assert cart["no_items_fit_budget"] is False
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/api/test_budget_fields_in_response.py -v`
Expected: FAIL — `KeyError: 'allowed_max'` (pydantic strips unknown dict keys not declared on `RetailerCart`).

- [ ] **Step 3: Update `app/api/schemas.py`**

In the `RetailerCart` model (lines 85-92), add the two fields:

```python
class RetailerCart(BaseModel):
    retailer: str
    items: list[CartLine]
    missing_items: list[dict]
    total: float
    budget: float | None
    allowed_max: float | None = None  # budget * 1.10; None when no budget was given
    over_budget_by: float | None
    no_items_fit_budget: bool = False  # True only for an open-ended/weekly-profile cart
    # where no candidate item could fit within allowed_max at all — the frontend must
    # never render this as a plain "successful" ₪0.00 cart.
    trade_off_suggestions: list[dict]
```

- [ ] **Step 4: Update `web/src/api.ts`**

In the `RetailerCart` interface (lines 57-66):

```typescript
export interface RetailerCart {
  retailer: string
  items: CartLine[]
  missing_items: Record<string, unknown>[]
  total: number
  budget: number | null
  allowed_max: number | null
  over_budget_by: number | null
  no_items_fit_budget: boolean
  trade_off_suggestions: Record<string, unknown>[]
  savings_vs_other?: number
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/api/test_budget_fields_in_response.py tests/api -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/api/schemas.py web/src/api.ts tests/api/test_budget_fields_in_response.py
git commit -m "feat(api): expose allowed_max and no_items_fit_budget on RetailerCart"
```

---

### Task 5: Frontend — show budget/tolerance/total and the empty-budget-cart message

**Files:**
- Modify: `web/src/components/retailers/RetailerCard.tsx`
- Modify: `web/src/components/chat/WarningsList.tsx`

**Interfaces:**
- Consumes: `RetailerCart.allowed_max`, `RetailerCart.no_items_fit_budget` (Task 4).

- [ ] **Step 1: Update `RetailerCard.tsx`**

Replace lines 14-65 (component start through the badges block):

```tsx
export function RetailerCard({ retailer, cart, selected, onChoose, chooseLabel }: RetailerCardProps) {
  const name = formatRetailerName(retailer)
  const hasBudget = cart.budget != null
  // Only a genuine overshoot past the 10% tolerance is treated as "over budget" — a
  // total between the requested budget and allowed_max is shown as a subtle note
  // instead (see below), never a warning-style badge.
  const overAllowedMax = hasBudget && cart.allowed_max != null && cart.total > cart.allowed_max
  const overBudgetWithinTolerance = hasBudget && !overAllowedMax && cart.total > cart.budget!
  const hasSavings = cart.savings_vs_other != null && cart.savings_vs_other > 0
  // A ₪0.00 cart with missing items has nothing to compare, not a bargain — flagged
  // clearly instead of silently looking like just a cheap/empty cart. A budget-only
  // cart where nothing could fit at all (see no_items_fit_budget) gets its own message.
  const isIncomplete = cart.total === 0 && cart.missing_items.length > 0 && !cart.no_items_fit_budget

  return (
    <div
      className={`flex flex-col rounded-3xl border bg-white p-5 transition ${
        selected ? 'border-blue-400 ring-2 ring-blue-200' : 'border-zinc-200'
      }`}
    >
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-zinc-100 text-zinc-500">
          <Store className="h-5 w-5" aria-hidden />
        </span>
        <span className="text-lg font-semibold text-zinc-900">{name}</span>
        {selected && (
          <Badge variant="secondary" className="ml-auto bg-blue-100 text-blue-700 hover:bg-blue-100">
            Selected
          </Badge>
        )}
      </div>

      <p className="mt-4 text-3xl font-bold text-zinc-900">₪{cart.total.toFixed(2)}</p>

      {hasBudget && (
        <p className="mt-1 text-xs text-zinc-500">
          Requested budget: ₪{cart.budget!.toFixed(2)}
          {cart.allowed_max != null && <> · Allowed tolerance: up to ₪{cart.allowed_max.toFixed(2)}</>}
        </p>
      )}
      {overBudgetWithinTolerance && (
        <p className="mt-1 text-xs text-amber-600">
          ₪{(cart.total - cart.budget!).toFixed(2)} above your target, within the allowed 10% tolerance.
        </p>
      )}

      <div className="mt-2 flex flex-wrap gap-2">
        {hasSavings && (
          <Badge variant="secondary" className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">
            Save ₪{cart.savings_vs_other!.toFixed(2)}
          </Badge>
        )}
        {isIncomplete && (
          <Badge variant="secondary" className="bg-amber-100 text-amber-800 hover:bg-amber-100">
            Incomplete cart
          </Badge>
        )}
        {hasBudget && (
          <Badge
            variant="secondary"
            className={
              overAllowedMax
                ? 'bg-red-100 text-red-700 hover:bg-red-100'
                : 'bg-emerald-100 text-emerald-700 hover:bg-emerald-100'
            }
          >
            {overAllowedMax ? `Over budget by ₪${cart.over_budget_by!.toFixed(2)}` : 'Under budget'}
          </Badge>
        )}
      </div>

      {cart.no_items_fit_budget && (
        <p className="mt-3 text-sm text-zinc-500">
          No suitable grocery items could be found within this budget.
        </p>
      )}
```

Leave the rest of the file (the items list, missing-items, trade-off suggestions, and choose button, lines 67-115 in the original) unchanged, but note `overAllowedMax` now controls the badge instead of the old `overBudget` variable name — remove the old `const overBudget = cart.over_budget_by != null` line entirely (it's replaced by `overAllowedMax`/`overBudgetWithinTolerance` above).

- [ ] **Step 2: Update `WarningsList.tsx`**

Add a branch in `formatWarning` (after the `budget_exceeded` branch, before `recipe_not_found`, in `web/src/components/chat/WarningsList.tsx`):

```typescript
  if (code === 'no_items_within_budget') {
    return 'No suitable grocery items could be found within this budget.'
  }
```

- [ ] **Step 3: Type-check and build**

Run: `cd /Users/moatazodeh/Documents/ai-supermarket-agent/web && npm run build`
Expected: succeeds with no TypeScript errors (this catches any prop/type mismatch from Task 4's interface change immediately).

- [ ] **Step 4: Lint**

Run: `npm run lint`
Expected: no new oxlint errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/retailers/RetailerCard.tsx web/src/components/chat/WarningsList.tsx
git commit -m "feat(web): show requested budget, tolerance, and empty-budget-cart messaging"
```

---

### Task 6: Full verification suite + manual Docker Compose check

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `cd /Users/moatazodeh/Documents/ai-supermarket-agent && make test`
Expected: all tests PASS, zero failures/errors.

- [ ] **Step 2: Run lint**

Run: `make lint`
Expected: clean (no ruff violations).

- [ ] **Step 3: Run coverage**

Run: `make coverage`
Expected: succeeds; note the coverage percentage for the final report (no enforced minimum found in `pyproject.toml`/CI config, so just confirm it runs clean and the new modules are exercised).

- [ ] **Step 4: Build the frontend**

Run: `cd web && npm run build`
Expected: succeeds (already verified in Task 5, re-run here as the final gate alongside the backend checks).

- [ ] **Step 5: Manual verification via Docker Compose**

Run: `docker compose up -d --build` (from repo root; requires `docker compose --profile tools run --rm ingestion` once beforehand per README if the DB hasn't been seeded yet).

In the web UI (`http://localhost:3000`):
1. Send "Build me a grocery cart for ₪20", answer the weekly-shop-profile clarification (e.g. "Basic essentials"). Expected: both retailer carts non-empty, each total ≤ ₪22, no "build everything then warn" behavior.
2. Send "Weekly shopping for one person under ₪100", choose "Weekly shop for one person". Expected: profile items selected progressively, each retailer ≤ ₪110.
3. Send "Milk, eggs, bread and chicken under ₪20". Expected: all four requested items remain the goal (added or reported missing, never silently dropped for budget reasons); if over budget, trade-off/over-budget info is shown, not a smaller substituted list.

Record actual observed totals/behavior for the final report.

- [ ] **Step 6: Tear down**

Run: `docker compose down`

---

## Self-Review Notes (for the plan author, not a task)

- Spec coverage check: budget formula/tolerance (Task 2), open-ended vs explicit distinction (Task 1 flag + Task 2 branch), progressive selection heuristics (Task 2, list order + cheapest-candidate), budget target closeness (Task 2 "skip and keep going" + test), per-retailer independence (Task 2 test), empty-cart protection (Task 2 + Task 3), weekly-profile + budget (Task 1 + Task 2, reuses existing profile flow), price calculations for weighted items (Task 2 `_estimated_cost`), frontend display (Task 5), all 12 required test scenarios (Tasks 2-4 tests) — all covered.
- No placeholders: every step has real, complete code.
- Type consistency: `open_ended_budget_selection` name matches between `state.py`, `resolve_weekly_shop_profile.py`, and `build_retailer_cart.py`; `allowed_max`/`no_items_fit_budget` names match across the cart dict, pydantic schema, and TS interface.
