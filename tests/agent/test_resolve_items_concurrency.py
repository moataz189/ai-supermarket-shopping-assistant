"""Proves resolve_items.py's relevance-filter LLM calls for independent items actually
overlap in time (asyncio.gather), not just that the final output is unchanged -- a purely
sequential `await` chain would also produce the same output, just slower. Real user
report (2026-08-15): a 6-item recipe across 2 retailers made up to 12 sequential
relevance-filter calls, confirmed live to take tens of seconds.
"""

import asyncio
import re
from types import SimpleNamespace

from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import FakeSupermarketDataClient


class _ConcurrencyTrackingLLM:
    """Like FakeLLM (see tests/agent/fakes.py), but the relevance-filter call path
    sleeps briefly and records the peak number of calls in flight at once."""

    def __init__(self, parsed):
        self._parsed = parsed
        self.in_flight = 0
        self.max_in_flight = 0

    def with_structured_output(self, schema, include_raw=False):
        return self

    async def ainvoke(self, messages):
        if len(messages) >= 2 and "Candidate product names:" in messages[-1][1]:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            await asyncio.sleep(0.05)
            self.in_flight -= 1
            names = re.findall(r"^- (.+)$", messages[-1][1], re.MULTILINE)
            return SimpleNamespace(content="\n".join(names) if names else "NONE")
        return {"raw": SimpleNamespace(content=None), "parsed": self._parsed, "parsing_error": None}


async def test_relevance_filter_calls_for_independent_items_run_concurrently():
    llm = _ConcurrencyTrackingLLM(parsed=ParsedRequestSchema(items=["a", "b", "c"]))
    candidates = {}
    prices = {}
    for name, code in [("a", "A"), ("b", "B"), ("c", "C")]:
        # 2+ candidates at Shufersal -- genuinely ambiguous, so each triggers its own
        # relevance-filter call. Exactly 1 at Rami Levy -- auto-resolves, no LLM call,
        # keeping the concurrency signal isolated to the calls under test.
        candidates[(name, "shufersal")] = [
            {"item_code": f"{code}1", "name": f"{name} Option 1", "price": 5.0},
            {"item_code": f"{code}2", "name": f"{name} Option 2", "price": 6.0},
        ]
        candidates[(name, "rami_levy")] = [{"item_code": f"{code}-R", "name": f"{name} Only", "price": 4.0}]
        prices[("rami_levy", f"{code}-R")] = {"unit_price": 4.0, "price": 4.0}
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t-concurrency"}}

    await app.ainvoke({"raw_message": "a, b, c"}, config=config)

    # 3 independent items each need a relevance-filter call -- a sequential await chain
    # would never have more than 1 in flight at once.
    assert llm.max_in_flight >= 2
