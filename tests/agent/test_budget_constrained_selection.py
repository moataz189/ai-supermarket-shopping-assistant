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
    # 0.4 kg requested, but חזה עוף is whole-kg-only (2026-08-16 fix) -> normalized to
    # 1.0 kg before pricing. 1.0 kg at ₪20/kg (unit_price 0.02 ₪/g) -> 0.02 * 1.0 * 1000
    # = ₪20.00, NOT the raw fractional 0.4 kg price (₪8.00) this test asserted before
    # that fix, and NOT the ₪20.0 raw package price a qty=1 assumption would have used.
    assert chicken["requested_quantity"] == 1.0
    assert chicken["subtotal"] == 20.0
    assert cart["total"] == 20.0


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
