# CP4 — LangGraph Agent: Grocery-List Core Flow

Spec milestone: M1. Depends on: CP2, CP3.

## Goal

Build the LangGraph agent for the **direct grocery-list path only** (no recipes yet):
parse → search → resolve ambiguity (auto-select where possible, interrupt otherwise) →
single-retailer optimize → finalize, using an in-memory/SQLite checkpointer so a paused
(awaiting-clarification) run resumes correctly. The product-selection/ambiguity-resolution
logic built here (spec §3, Product Selection & Ambiguity Resolution) is not
grocery-list-specific — CP7 feeds recipe-derived ingredients through this exact same logic
without modifying it.

## Scope

The graph, its state schema, its nodes, the MCP client wrapper for the Supermarket-Data MCP
server (CP3), and the checkpointer seam (memory/SQLite now; DynamoDB added in CP11 without
changing this code). All external calls (Bedrock, MCP server) are injected as dependencies
so tests run with fakes — no live network calls.

## Deliverables

- `build_graph(client, llm, checkpointer)` returns a compiled, invokable LangGraph app.
- Given a fake supermarket client and a fake LLM, the graph resolves a direct grocery list
  to a single-retailer cart: auto-selecting when a choice isn't genuinely ambiguous (one
  candidate, a brand match, or a "cheapest" standing preference), pausing to ask only when
  it is, and reporting missing items — all covered by tests, no network calls.

## Files to Create

```
app/agent/__init__.py
app/agent/state.py
app/agent/llm.py
app/agent/mcp_clients.py
app/agent/checkpointer.py
app/agent/nodes/__init__.py
app/agent/nodes/parse_request.py
app/agent/nodes/search_products.py
app/agent/nodes/resolve_ambiguity.py
app/agent/nodes/optimize_cart.py
app/agent/nodes/finalize.py
app/agent/graph.py
tests/agent/fakes.py
tests/agent/test_graph_grocery_list_happy_path.py
tests/agent/test_graph_ambiguous_product_interrupt.py
tests/agent/test_graph_missing_item.py
tests/agent/test_optimize_cart_unit.py
tests/agent/test_ambiguity_resolution_rules.py
```

## Detailed Implementation Steps

1. Write `app/agent/state.py`:
   ```python
   from typing import Literal, TypedDict


   class ParsedItem(TypedDict):
       name: str
       quantity: float | None


   class ParsedRequest(TypedDict):
       items: list[ParsedItem]
       budget: float | None
       dietary_constraints: list[str]
       retailer_preference: str | None
       brand_preference: str | None
       selection_preference: Literal["cheapest", "no_preference"]


   class AgentState(TypedDict, total=False):
       raw_message: str
       parsed_request: ParsedRequest
       item_candidates: dict[str, list[dict]]
       resolved_choices: dict[str, str]
       pending_clarification_item: str | None
       cart: list[dict]
       chosen_retailer: str | None
       cart_total: float
       missing_items: list[dict]
       warnings: list[dict]
       status: Literal["success", "partial_success", "needs_clarification"]
       clarification: dict | None
       final_cart: dict
   ```
2. Write `app/agent/mcp_clients.py` with a `SupermarketDataClient` protocol and the real
   stdio-based implementation talking to CP3's server:
   ```python
   from typing import Protocol

   from mcp import ClientSession, StdioServerParameters
   from mcp.client.stdio import stdio_client


   class SupermarketDataClient(Protocol):
       async def search_product(self, query: str, retailer: str | None = None) -> list[dict]: ...
       async def get_product_offers(self, product_id: str) -> list[dict]: ...


   class McpSupermarketDataClient:
       def __init__(self, command: str, args: list[str]):
           self._params = StdioServerParameters(command=command, args=args)

       async def _call(self, tool_name: str, arguments: dict) -> dict:
           async with stdio_client(self._params) as (read, write):
               async with ClientSession(read, write) as session:
                   await session.initialize()
                   result = await session.call_tool(tool_name, arguments)
                   return result.structuredContent or {}

       async def search_product(self, query: str, retailer: str | None = None) -> list[dict]:
           result = await self._call("search_product", {"query": query, "retailer": retailer})
           return result.get("candidates", [])

       async def get_product_offers(self, product_id: str) -> list[dict]:
           result = await self._call("get_product_offers", {"product_id": product_id})
           return result.get("offers", [])
   ```
3. Write `tests/agent/fakes.py` with `FakeSupermarketDataClient` (constructed with canned
   `search_product`/`get_product_offers` return values per query/product_id, set up per
   test) and `FakeLLM` (a callable returning a canned `ParsedRequestSchema` regardless of
   input, so `parse_request` is testable without Bedrock).
4. Write `app/agent/llm.py`:
   ```python
   import os

   from langchain_aws import ChatBedrockConverse


   def get_llm():
       return ChatBedrockConverse(
           model=os.environ["BEDROCK_MODEL_ID"],
           region_name=os.environ.get("AWS_REGION", "us-east-1"),
           temperature=0,
       )
   ```
5. Write `app/agent/nodes/parse_request.py` as a factory so the LLM is injectable. Besides
   the shopping list itself, this extracts the standing **product-selection preference**
   (spec §3): `"cheapest"` if the user said something like "whatever's cheapest" / "the
   cheapest option", otherwise `"no_preference"` (the default — ask when a choice is
   ambiguous and material). Note that "vegan only" / "gluten-free only" standing preferences
   are **not** a separate field — they're captured the same way any other dietary
   restriction is, via `dietary_constraints` (already enforced deterministically by CP7's
   dietary rule engine, not duplicated here):
   ```python
   from typing import Literal

   from pydantic import BaseModel

   from app.agent.state import AgentState

   PARSE_PROMPT = (
       "Extract a structured shopping list from the user's message. "
       "List each grocery/household item as a separate string in `items`, "
       "singular, without quantities. Extract `budget` (a number, no currency "
       "symbol) if stated. Extract `dietary_constraints` as short tags "
       "(e.g. 'no dairy', 'vegan', 'gluten free') — this is also where a stated "
       "'vegan only' or 'gluten-free only' preference belongs, not a separate field. "
       "Extract `retailer_preference` ('shufersal' or 'rami_levy') and "
       "`brand_preference` only if explicitly stated. Extract `selection_preference` "
       "as 'cheapest' only if the user asked for the cheapest/lowest-price option "
       "whenever a choice comes up; otherwise 'no_preference'."
   )


   class ParsedRequestSchema(BaseModel):
       items: list[str]
       budget: float | None = None
       dietary_constraints: list[str] = []
       retailer_preference: str | None = None
       brand_preference: str | None = None
       selection_preference: Literal["cheapest", "no_preference"] = "no_preference"


   def make_parse_request(llm):
       structured_llm = llm.with_structured_output(ParsedRequestSchema)

       async def parse_request(state: AgentState) -> AgentState:
           result: ParsedRequestSchema = await structured_llm.ainvoke(
               [("system", PARSE_PROMPT), ("user", state["raw_message"])]
           )
           return {
               "parsed_request": {
                   "items": [{"name": n, "quantity": None} for n in result.items],
                   "budget": result.budget,
                   "dietary_constraints": result.dietary_constraints,
                   "retailer_preference": result.retailer_preference,
                   "brand_preference": result.brand_preference,
                   "selection_preference": result.selection_preference,
               }
           }

       return parse_request
   ```
6. Write `app/agent/nodes/search_products.py`. This implements spec §3's Product Selection
   & Ambiguity Resolution rules — applied identically to every item regardless of whether it
   came from a direct grocery list (this checkpoint) or a recipe (CP7 feeds ingredients into
   the same node unchanged):
   - Zero or one candidate → nothing to ask (handled downstream as missing / auto-selected).
   - Exactly one candidate's name exactly matches the query → auto-select it.
   - A `brand_preference` is set and exactly one candidate's name contains it → auto-select
     that one.
   - `selection_preference == "cheapest"` and at least one candidate has offer data → fetch
     offers for each candidate and auto-select the one with the lowest `unit_price`.
   - Otherwise → still ambiguous; the caller will interrupt and show the (≤5) candidates.
   ```python
   from app.agent.state import AgentState


   async def _resolve_candidate(
       client, name: str, candidates: list[dict], brand_preference: str | None,
       selection_preference: str,
   ) -> tuple[str | None, bool]:
       """Returns (resolved_product_id_or_None, still_ambiguous)."""
       if len(candidates) <= 1:
           return (candidates[0]["product_id"] if candidates else None), False

       exact = [c for c in candidates if c["name"].strip().lower() == name.strip().lower()]
       if len(exact) == 1:
           return exact[0]["product_id"], False

       if brand_preference:
           brand_matches = [
               c for c in candidates if brand_preference.strip().lower() in c["name"].strip().lower()
           ]
           if len(brand_matches) == 1:
               return brand_matches[0]["product_id"], False

       if selection_preference == "cheapest":
           priced: list[tuple[str, float]] = []
           for candidate in candidates:
               offers = await client.get_product_offers(candidate["product_id"])
               if offers:
                   cheapest_offer = min(offers, key=lambda o: o["unit_price"])
                   priced.append((candidate["product_id"], cheapest_offer["unit_price"]))
           if priced:
               best_id, _ = min(priced, key=lambda p: p[1])
               return best_id, False

       return None, True


   def make_search_products(client):
       async def search_products(state: AgentState) -> AgentState:
           parsed = state["parsed_request"]
           item_candidates = dict(state.get("item_candidates", {}))
           resolved_choices = dict(state.get("resolved_choices", {}))
           ambiguous_item = None

           for item in parsed["items"]:
               name = item["name"]
               if name in resolved_choices:
                   continue
               if name not in item_candidates:
                   item_candidates[name] = await client.search_product(name)
               candidates = item_candidates[name]

               resolved_id, still_ambiguous = await _resolve_candidate(
                   client, name, candidates,
                   parsed.get("brand_preference"), parsed.get("selection_preference", "no_preference"),
               )
               if resolved_id is not None:
                   resolved_choices[name] = resolved_id
               elif still_ambiguous and ambiguous_item is None:
                   ambiguous_item = name

           return {
               "item_candidates": item_candidates,
               "resolved_choices": resolved_choices,
               "pending_clarification_item": ambiguous_item,
           }

       return search_products
   ```
7. Write `app/agent/nodes/resolve_ambiguity.py`. Per spec §3, show a small, relevant
   shortlist (3–5), never an exhaustive list — cap at 5 even though `search_product`
   already defaults to a limit of 5 candidates (CP2), so this stays correct even if that
   default ever changes:
   ```python
   from langgraph.types import interrupt

   from app.agent.state import AgentState

   MAX_CANDIDATES_SHOWN = 5


   async def resolve_ambiguity(state: AgentState) -> AgentState:
       item_name = state["pending_clarification_item"]
       candidates = state["item_candidates"][item_name][:MAX_CANDIDATES_SHOWN]
       answer = interrupt(
           {
               "reason": "ambiguous_product",
               "question": f"I found a few options for '{item_name}' — which one did you mean?",
               "options": [{"id": c["product_id"], "label": c["name"]} for c in candidates],
           }
       )
       resolved = {**state.get("resolved_choices", {}), item_name: answer}
       return {"resolved_choices": resolved, "pending_clarification_item": None}
   ```
8. Write `app/agent/nodes/optimize_cart.py` implementing single-retailer selection
   (spec §4 step 8: prefer a retailer that fully covers the cart; if none does, best
   coverage+cost combination). Each resolved item's `product_id` is looked up via
   `get_product_offers`, which returns that same product's offer — identified by its
   `ItemCode` — at each retailer's Online store (`StoreId 413` / `39`); the `item_code` and
   `store_id` are carried through onto each cart line so the final cart is traceable back to
   exactly what was compared:
   ```python
   from app.agent.state import AgentState


   def make_optimize_cart(client):
       async def optimize_cart(state: AgentState) -> AgentState:
           retailer_lines: dict[str, list[dict]] = {"shufersal": [], "rami_levy": []}
           missing_items = list(state.get("missing_items", []))

           for item in state["parsed_request"]["items"]:
               name = item["name"]
               product_id = state.get("resolved_choices", {}).get(name)
               if product_id is None:
                   candidates = state["item_candidates"].get(name, [])
                   if len(candidates) == 1:
                       product_id = candidates[0]["product_id"]
                   elif not candidates:
                       missing_items.append({"name": name, "reason": "not_found"})
                       continue
                   else:
                       continue

               offers = await client.get_product_offers(product_id)
               for offer in offers:
                   retailer_lines[offer["retailer"]].append(
                       {
                           "product_id": product_id,
                           "name": name,
                           "retailer": offer["retailer"],
                           "item_code": offer["item_code"],
                           "store_id": offer["store_id"],
                           "unit_price": offer["unit_price"],
                           "price": offer["price"],
                       }
                   )

           requested = len(state["parsed_request"]["items"]) - len(missing_items)
           scored = [
               (retailer, len(lines), sum(line["price"] for line in lines))
               for retailer, lines in retailer_lines.items()
           ]
           full_coverage = [s for s in scored if s[1] == requested]
           best = min(full_coverage, key=lambda s: s[2]) if full_coverage else max(
               scored, key=lambda s: (s[1], -s[2])
           )
           retailer, _coverage, total = best

           cart = [{**line, "qty": 1, "subtotal": line["price"]} for line in retailer_lines[retailer]]
           covered_names = {line["name"] for line in cart}
           for item in state["parsed_request"]["items"]:
               already_missing = any(m["name"] == item["name"] for m in missing_items)
               if item["name"] not in covered_names and not already_missing:
                   missing_items.append({"name": item["name"], "reason": "not_available_at_chosen_retailer"})

           return {"cart": cart, "missing_items": missing_items, "chosen_retailer": retailer, "cart_total": total}

       return optimize_cart
   ```
9. Write `app/agent/nodes/finalize.py`:
   ```python
   from app.agent.state import AgentState


   def finalize(state: AgentState) -> AgentState:
       budget = state["parsed_request"].get("budget")
       total = state.get("cart_total", 0.0)
       warnings = list(state.get("warnings", []))

       if state.get("missing_items"):
           warnings.append({"code": "product_not_found", "items": state["missing_items"]})

       over_budget_by = None
       if budget is not None and total > budget:
           over_budget_by = round(total - budget, 2)
           warnings.append({"code": "budget_exceeded", "over_budget_by": over_budget_by})

       return {
           "status": "partial_success" if warnings else "success",
           "warnings": warnings,
           "clarification": None,
           "final_cart": {
               "retailer": state.get("chosen_retailer"),
               "items": state.get("cart", []),
               "total": total,
               "budget": budget,
               "over_budget_by": over_budget_by,
           },
       }
   ```
10. Write `app/agent/checkpointer.py`:
    ```python
    import os

    from langgraph.checkpoint.memory import MemorySaver


    def get_checkpointer():
        backend = os.environ.get("CHECKPOINTER_BACKEND", "memory")
        if backend == "memory":
            return MemorySaver()
        if backend == "sqlite":
            from langgraph.checkpoint.sqlite import SqliteSaver

            return SqliteSaver.from_conn_string(
                os.environ.get("CHECKPOINTER_SQLITE_PATH", "checkpoints.db")
            )
        raise ValueError(
            f"Unsupported CHECKPOINTER_BACKEND {backend!r} as of CP4 "
            "('dynamodb' is added in CP11)"
        )
    ```
11. Write `app/agent/graph.py` wiring the conditional edge that routes to
    `resolve_ambiguity` whenever `pending_clarification_item` is set, and loops back to
    `search_products` afterward so remaining items get their turn:
    ```python
    from langgraph.graph import END, START, StateGraph

    from app.agent.nodes.finalize import finalize
    from app.agent.nodes.optimize_cart import make_optimize_cart
    from app.agent.nodes.parse_request import make_parse_request
    from app.agent.nodes.resolve_ambiguity import resolve_ambiguity
    from app.agent.nodes.search_products import make_search_products
    from app.agent.state import AgentState


    def _route_after_search(state: AgentState) -> str:
        return "resolve_ambiguity" if state.get("pending_clarification_item") else "optimize_cart"


    def build_graph(client, llm, checkpointer):
        graph = StateGraph(AgentState)
        graph.add_node("parse_request", make_parse_request(llm))
        graph.add_node("search_products", make_search_products(client))
        graph.add_node("resolve_ambiguity", resolve_ambiguity)
        graph.add_node("optimize_cart", make_optimize_cart(client))
        graph.add_node("finalize", finalize)

        graph.add_edge(START, "parse_request")
        graph.add_edge("parse_request", "search_products")
        graph.add_conditional_edges(
            "search_products", _route_after_search, ["resolve_ambiguity", "optimize_cart"]
        )
        graph.add_edge("resolve_ambiguity", "search_products")
        graph.add_edge("optimize_cart", "finalize")
        graph.add_edge("finalize", END)

        return graph.compile(checkpointer=checkpointer)
    ```
12. Write `tests/agent/test_graph_grocery_list_happy_path.py`: build the graph with
    `FakeSupermarketDataClient` returning one unambiguous candidate per item and offers
    making one retailer both fully-covering and cheaper; `FakeLLM` returning a fixed
    `ParsedRequestSchema`; invoke with `{"configurable": {"thread_id": "t1"}}`; assert
    `result["status"] == "success"` and `result["final_cart"]["retailer"]` matches the
    cheaper fully-covering retailer.
13. Write `tests/agent/test_graph_ambiguous_product_interrupt.py`: fake client returns two
    non-exact-matching candidates for one item; invoke the graph and assert the result
    carries a LangGraph interrupt payload with the expected `question`/`options`; resume
    with `graph.invoke(Command(resume=candidate_id), config=...)` using the **same**
    `thread_id`; assert the second invocation completes with that item resolved to the
    chosen `product_id` in the final cart.
14. Write `tests/agent/test_graph_missing_item.py`: fake client returns zero candidates for
    one item; assert `missing_items` contains it with `reason: "not_found"`,
    `status == "partial_success"`, and the rest of the cart is still built.
15. Write `tests/agent/test_optimize_cart_unit.py`: call `make_optimize_cart(fake_client)`
    directly with a hand-built state where neither retailer fully covers the list; assert
    it picks the retailer with the best coverage+cost combination, per spec §4 step 8.
16. Write `tests/agent/test_ambiguity_resolution_rules.py`, calling `_resolve_candidate`
    directly (unit-level, no graph):
    - Three candidates, `brand_preference="Tara"`, exactly one candidate name contains
      "Tara" → resolves to that candidate's `product_id`, `still_ambiguous is False`.
    - Three candidates, `selection_preference="cheapest"`, fake client's
      `get_product_offers` returns different `unit_price`s per candidate → resolves to the
      candidate with the lowest `unit_price`.
    - Three candidates, no brand preference, `selection_preference="no_preference"`, no
      exact name match → returns `(None, True)` (still ambiguous — the caller must ask).
    - One candidate → resolves to it automatically regardless of any preference.
17. Run `pytest tests/agent -v`, iterate to green; `ruff check`; commit.

## Testing Tasks

- [ ] Happy path: direct grocery list → correct single-retailer cart.
- [ ] Ambiguous product match → interrupt → resume with same `thread_id` → correct
      resolution.
- [ ] Missing item → reported with reason, rest of cart unaffected.
- [ ] `optimize_cart` unit test for the no-full-coverage scoring branch.
- [ ] Ambiguity-resolution rules unit tests: brand-preference auto-select, cheapest-preference
      auto-select, no-preference-still-ambiguous, single-candidate auto-select.
- [ ] Resolved cart lines carry `item_code` and `store_id` through to the final cart.
- [ ] All tests run with fakes only — zero live network/Bedrock/MCP-process calls.

## Acceptance Criteria

Given a fake LLM and fake MCP client, the compiled graph correctly handles: full-coverage
happy path, ambiguous-match interrupt/resume (using the checkpointer, keyed by `thread_id`),
missing items, and the auto-select rules (single candidate, brand match, cheapest
preference) that avoid asking when the choice isn't genuinely ambiguous — matching spec §3,
§4, and §8 exactly, with no recipe-path code yet (CP7).

## Risks

- LangGraph's exact interrupt/`Command(resume=...)` API surface can shift between minor
  versions — pin the `langgraph` version in `pyproject.toml` and re-check this checkpoint's
  test against that pinned version before moving on.
- Running `search_product` sequentially per item is simple but slow for long lists — track
  as a possible follow-up optimization (parallelize with `asyncio.gather`), not required for
  MVP correctness.
- The `selection_preference == "cheapest"` path calls `get_product_offers` once per
  candidate to compare prices before resolving — more MCP round-trips than the other
  auto-select paths, but only triggered when a choice would otherwise require asking, so the
  trade-off favors fewer clarification questions over raw speed.

## Notes

CP5 wraps this graph behind FastAPI, translating `final_cart`/`status`/`warnings`/interrupt
payloads into the `docs/plan/05-fastapi-react-ui.md` API contract. CP7 adds the recipe
branch ahead of `search_products` and layers the dietary rule engine in; it must not modify
the shape of `optimize_cart`/`finalize` from this checkpoint. CP8 later extends this graph's
terminal edge — `finalize` currently connects straight to `END`; CP8 inserts a cart-approval
interrupt and, if approved, a Playwright-based cart-preparation node between `finalize` and
`END`. Nothing in this checkpoint needs to anticipate that; CP8's own "Files to Modify"
section covers the change to `app/agent/graph.py`.

## Definition of Done

- [ ] All nodes and the compiled graph exist and are wired as above.
- [ ] All four tests pass using fakes only; `ruff check` clean.
- [ ] Committed with message referencing CP4.
