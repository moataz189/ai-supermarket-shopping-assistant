"""Unit tests for build_retailer_cart.py's own relevance filtering on its independent,
second catalog search (by the already-resolved label) -- separate from resolve_items.py's
own filtering on the *first* search. Real user report (2026-08-14): resolve_items.py's
filter can correctly narrow its own candidates, but this second search re-queries the
catalog from scratch and previously fed the raw result straight to `min(price)` with no
semantic check at all -- a cheap prepared "mashed potato with onion" dish won on price
alone for a plain "onion" search, at a wildly inflated cost, because nothing here ever
excluded it.
"""

from app.agent.nodes.build_retailer_cart import _add_every_item
from tests.agent.fakes import FakeLLM


class _StubClient:
    """Minimal search_product/get_product_price stub -- deliberately not
    FakeSupermarketDataClient (that fake key mismatches here would silently swallow):
    this test cares only about a single label's candidate list and the resulting pick."""

    def __init__(self, candidates: list[dict]):
        self._candidates = candidates
        self._prices = {c["item_code"]: c for c in candidates}

    async def search_product(self, query, retailer):
        return self._candidates

    async def get_product_price(self, retailer, item_code):
        c = self._prices[item_code]
        return {"price": c["price"], "unit_price": c["price"], "package_size": None, "package_unit": None}


WRONG_BUT_CHEAPER = {"item_code": "S-DISH", "name": "מנה חמה פירה עם בצל", "price": 5.0}
REAL_ONION = {"item_code": "S-ONION", "name": "בצל אדום", "price": 8.0}


async def test_second_search_relevance_filter_excludes_a_cheaper_irrelevant_candidate():
    # WRONG_BUT_CHEAPER is cheaper than REAL_ONION -- a bare min(price) pick would choose
    # it. The relevance filter (configured here to only accept the real onion) must
    # exclude it before price comparison ever happens.
    client = _StubClient([WRONG_BUT_CHEAPER, REAL_ONION])
    llm = FakeLLM(relevant_names=["בצל אדום"])
    items = [{"name": "onion", "search_name": "בצל"}]

    lines, missing = await _add_every_item(client, llm, "shufersal", items, {}, set(), [])

    assert missing == []
    assert len(lines) == 1
    assert lines[0]["item_code"] == "S-ONION"
    assert lines[0]["product_name"] == "בצל אדום"


async def test_second_search_falls_back_to_not_found_when_nothing_is_relevant():
    # The LLM judging *nothing* relevant must not fall back to the cheapest raw hit --
    # that's exactly the guess this filter exists to prevent. Two candidates (not one) so
    # the filter actually runs -- a lone candidate is accepted directly (see the "skips
    # the LLM call" test below), which would make this test pass for the wrong reason.
    client = _StubClient([WRONG_BUT_CHEAPER, REAL_ONION])
    llm = FakeLLM(relevant_names=[])
    items = [{"name": "onion", "search_name": "בצל"}]

    lines, missing = await _add_every_item(client, llm, "shufersal", items, {}, set(), [])

    assert lines == []
    assert missing == [{"name": "onion", "reason": "not_found"}]


async def test_second_search_skips_the_llm_call_for_a_single_candidate():
    # Matches the same cheap-path optimization used throughout resolve_items.py -- a lone
    # candidate is accepted directly, no LLM round trip for something there's no choice
    # to make about. Configuring relevant_names=[] on the FakeLLM would make this test
    # fail loudly if the filter were (incorrectly) invoked anyway.
    client = _StubClient([REAL_ONION])
    llm = FakeLLM(relevant_names=[])
    items = [{"name": "onion", "search_name": "בצל"}]

    lines, missing = await _add_every_item(client, llm, "shufersal", items, {}, set(), [])

    assert missing == []
    assert len(lines) == 1
    assert lines[0]["item_code"] == "S-ONION"


async def test_second_search_skips_the_llm_call_when_a_candidate_matches_the_label_exactly():
    # Real user report (2026-08-16): a "tomato" search kept adding "רוטב עגבניות"
    # (tomato sauce, ₪14.50) instead of the plain "עגבניה" (tomato, ₪2.00) product sitting
    # right there in the same candidate list -- resolve_items.py's own _resolve_item has
    # an exact-match shortcut that skips the LLM entirely, but this second, independent
    # search had no equivalent, so it stayed exposed to relevance-filter LLM
    # non-determinism even when a deterministic exact match existed. Configuring
    # relevant_names=[] on the FakeLLM would make this test fail loudly (falling back to
    # "not_found") if the shortcut were missing and the LLM's (wrong) answer were trusted.
    sauce = {"item_code": "S-SAUCE", "name": "רוטב עגבניות", "price": 14.5}
    real_tomato = {"item_code": "S-TOM", "name": "עגבניה", "price": 2.0}
    client = _StubClient([sauce, real_tomato])
    llm = FakeLLM(relevant_names=[])
    items = [{"name": "tomato", "search_name": "עגבניה"}]

    lines, missing = await _add_every_item(client, llm, "shufersal", items, {}, set(), [])

    assert missing == []
    assert len(lines) == 1
    assert lines[0]["item_code"] == "S-TOM"
    assert lines[0]["product_name"] == "עגבניה"


async def test_second_search_still_relevance_filters_when_no_candidate_matches_the_label_exactly():
    # The exact-match shortcut must not swallow genuine ambiguity -- when nothing matches
    # the label verbatim (both candidates are qualified/compound names), relevance
    # filtering still runs as before.
    client = _StubClient([WRONG_BUT_CHEAPER, REAL_ONION])
    llm = FakeLLM(relevant_names=["בצל אדום"])
    items = [{"name": "onion", "search_name": "בצל"}]

    lines, missing = await _add_every_item(client, llm, "shufersal", items, {}, set(), [])

    assert missing == []
    assert len(lines) == 1
    assert lines[0]["item_code"] == "S-ONION"
