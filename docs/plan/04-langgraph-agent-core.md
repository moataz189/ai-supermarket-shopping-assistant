# CP4 — LangGraph Agent: Grocery-List Core Flow

Spec milestone: M1. Depends on: CP2, CP3.

## Goal

Build the LangGraph agent for the **direct grocery-list path only** (no recipes yet):
parse → resolve items (once, across both retailers) → build a cart **independently for each
retailer** → compare the two → interrupt asking the user to choose one (or decline). Uses an
in-memory/SQLite checkpointer so a paused run resumes correctly. This is the same logic CP7
reuses unmodified for recipe-derived ingredients.

## Scope

The graph, its state, its nodes, the MCP client wrapper for the Supermarket-Data MCP server
(CP3), and the checkpointer seam (memory/SQLite now; DynamoDB in CP11). External calls
(Bedrock, MCP server) are injected so tests use fakes — no live network calls.

## Deliverables

- `build_graph(client, llm, checkpointer)` returns a compiled, invokable LangGraph app.
- Given fakes, the graph: resolves each item once (auto-selecting when unambiguous, asking
  otherwise), builds two independent carts (Shufersal, Rami Levy) — each respecting budget/
  dietary/brand/price — and pauses for the user to choose one or decline.

## Files to Create

```
app/agent/__init__.py
app/agent/state.py
app/agent/llm.py
app/agent/mcp_clients.py
app/agent/checkpointer.py
app/agent/nodes/__init__.py
app/agent/nodes/parse_request.py
app/agent/nodes/resolve_items.py
app/agent/nodes/resolve_ambiguity.py
app/agent/nodes/build_retailer_cart.py
app/agent/nodes/choose_retailer.py
app/agent/nodes/finalize.py
app/agent/graph.py
tests/agent/fakes.py
tests/agent/test_graph_two_retailer_carts_happy_path.py
tests/agent/test_graph_ambiguous_item_interrupt.py
tests/agent/test_graph_missing_item_one_retailer.py
tests/agent/test_budget_trade_off_suggestion.py
tests/agent/test_choose_retailer_decline.py
tests/agent/test_resolve_item_rules.py
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
       item_candidates: dict[str, dict[str, list[dict]]]  # item name -> retailer -> candidates
       resolved_choices: dict[str, str]          # item name -> resolved label
       pending_clarification_item: str | None
       retailer_carts: dict[str, dict]           # "shufersal"/"rami_levy" -> cart dict
       chosen_retailer: str | None
       warnings: list[dict]
       status: Literal["success", "partial_success", "needs_clarification", "awaiting_retailer_choice"]
       clarification: dict | None
       final_result: dict
   ```
   `retailer_preference` is extracted but not used to skip building a cart in the MVP — both
   retailers are always built; it may only inform how the choice is presented later (CP16).
2. Write `app/agent/mcp_clients.py`. `search_product` and `get_product_price` both take a
   required `retailer` — this server never mixes retailers in one call. **All MCP servers in
   this project are long-lived HTTP services** (CP3/CP6/CP8), not subprocesses spawned per
   call — the client connects to a URL over the MCP "streamable HTTP" transport:
   ```python
   from typing import Protocol

   from mcp import ClientSession
   from mcp.client.streamable_http import streamablehttp_client


   class SupermarketDataClient(Protocol):
       async def search_product(self, query: str, retailer: str) -> list[dict]: ...
       async def get_product_price(self, retailer: str, item_code: str) -> dict | None: ...


   class McpSupermarketDataClient:
       def __init__(self, base_url: str):
           self.base_url = base_url  # e.g. "http://supermarket-mcp:8001/mcp"

       async def _call(self, tool_name: str, arguments: dict) -> dict | None:
           async with streamablehttp_client(self.base_url) as (read, write, _):
               async with ClientSession(read, write) as session:
                   await session.initialize()
                   result = await session.call_tool(tool_name, arguments)
                   return result.structuredContent

       async def search_product(self, query: str, retailer: str) -> list[dict]:
           result = await self._call("search_product", {"query": query, "retailer": retailer})
           return (result or {}).get("candidates", [])

       async def get_product_price(self, retailer: str, item_code: str) -> dict | None:
           return await self._call("get_product_price", {"retailer": retailer, "item_code": item_code})
   ```
   Verify `streamablehttp_client`'s exact import path/signature against the pinned `mcp` SDK
   version (this transport is relatively new and the API has moved between releases).
3. Write `tests/agent/fakes.py`: `FakeSupermarketDataClient`, constructed with a
   `{(query, retailer): [candidates]}` map and a `{(retailer, item_code): price_dict}` map,
   so a test can give Shufersal and Rami Levy different candidates/prices for the same item
   name; `FakeLLM` returns a canned `ParsedRequestSchema`.
4. Write `app/agent/llm.py` (unchanged pattern):
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
5. Write `app/agent/nodes/parse_request.py`:
   ```python
   from typing import Literal

   from pydantic import BaseModel

   from app.agent.state import AgentState

   PARSE_PROMPT = (
       "Extract a structured shopping list from the user's message. List each "
       "grocery/household item as a separate string in `items`, singular, without "
       "quantities. Extract `budget` (a number, no currency symbol) if stated. Extract "
       "`dietary_constraints` as short tags (e.g. 'no dairy', 'vegan') — a stated 'vegan "
       "only'/'gluten-free only' preference belongs here too. Extract `retailer_preference` "
       "('shufersal' or 'rami_levy') and `brand_preference` only if explicitly stated. "
       "Extract `selection_preference` as 'cheapest' only if the user asked for the "
       "cheapest option whenever a choice comes up; otherwise 'no_preference'."
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
           return {"parsed_request": {
               "items": [{"name": n, "quantity": None} for n in result.items],
               "budget": result.budget,
               "dietary_constraints": result.dietary_constraints,
               "retailer_preference": result.retailer_preference,
               "brand_preference": result.brand_preference,
               "selection_preference": result.selection_preference,
           }}

       return parse_request
   ```
6. Write `app/agent/nodes/resolve_items.py` — resolves each item **once**, against a
   shortlist merged across both retailers (spec §3):
   ```python
   from app.agent.state import AgentState

   RETAILERS = ["shufersal", "rami_levy"]


   async def _candidates_by_retailer(client, name: str) -> dict[str, list[dict]]:
       """Keeps each retailer's candidates separate — never merged away — so the user can
       see which retailer actually carries which option before choosing (spec §3)."""
       return {retailer: await client.search_product(name, retailer) for retailer in RETAILERS}


   def _unique_labels(candidates_by_retailer: dict[str, list[dict]]) -> list[dict]:
       """Dedups by name *across* retailers into the set of distinct 'kinds' the user might
       mean — used only to decide/present what to resolve, never to build a cart directly."""
       merged: dict[str, dict] = {}
       for candidates in candidates_by_retailer.values():
           for c in candidates:
               merged.setdefault(c["name"].strip().lower(), c)
       return list(merged.values())[:5]


   async def _resolve_item(
       name: str, candidates: list[dict], brand_preference: str | None, selection_preference: str,
   ) -> tuple[str | None, bool]:
       """`candidates` is the deduped, cross-retailer set from `_unique_labels`. Returns
       (resolved_label_or_None, still_ambiguous). A resolved label is a product name used as
       the search query in each retailer's own catalog later — not an item_code."""
       if not candidates:
           return name, False  # nothing matched anywhere; let per-retailer building report it missing
       if len(candidates) == 1:
           return candidates[0]["name"], False

       exact = [c for c in candidates if c["name"].strip().lower() == name.strip().lower()]
       if len(exact) == 1:
           return exact[0]["name"], False

       if brand_preference:
           matches = [c for c in candidates if brand_preference.strip().lower() in c["name"].strip().lower()]
           if len(matches) == 1:
               return matches[0]["name"], False

       if selection_preference == "cheapest":
           return min(candidates, key=lambda c: c["price"])["name"], False

       return None, True


   def make_resolve_items(client):
       async def resolve_items(state: AgentState) -> AgentState:
           parsed = state["parsed_request"]
           item_candidates = dict(state.get("item_candidates", {}))
           resolved_choices = dict(state.get("resolved_choices", {}))
           ambiguous_item = None

           for item in parsed["items"]:
               name = item["name"]
               if name in resolved_choices:
                   continue
               if name not in item_candidates:
                   item_candidates[name] = await _candidates_by_retailer(client, name)
               by_retailer = item_candidates[name]

               label, still_ambiguous = await _resolve_item(
                   name, _unique_labels(by_retailer),
                   parsed.get("brand_preference"), parsed.get("selection_preference", "no_preference"),
               )
               if label is not None:
                   resolved_choices[name] = label
               elif still_ambiguous and ambiguous_item is None:
                   ambiguous_item = name

           return {
               "item_candidates": item_candidates,
               "resolved_choices": resolved_choices,
               "pending_clarification_item": ambiguous_item,
           }

       return resolve_items
   ```
   `item_candidates` is now `dict[str, dict[str, list[dict]]]` — item name → retailer →
   that retailer's own candidates (update the type hint in `app/agent/state.py`,
   step 1, accordingly: `item_candidates: dict[str, dict[str, list[dict]]]`).
7. Write `app/agent/nodes/resolve_ambiguity.py` — when asking, show **both** the
   selectable (deduped) options *and* the per-retailer breakdown, e.g. "Shufersal: Tnuva,
   Tara / Rami Levy: Tnuva, President", so the user knows what's actually available where
   before picking:
   ```python
   from langgraph.types import interrupt

   from app.agent.nodes.resolve_items import _unique_labels

   MAX_CANDIDATES_SHOWN = 5


   async def resolve_ambiguity(state):
       item_name = state["pending_clarification_item"]
       by_retailer = state["item_candidates"][item_name]
       unique = _unique_labels(by_retailer)[:MAX_CANDIDATES_SHOWN]

       answer = interrupt({
           "reason": "ambiguous_product",
           "question": f"I found a few options for '{item_name}' — which one did you mean?",
           "options": [{"id": c["name"], "label": c["name"]} for c in unique],
           "availability_by_retailer": {
               retailer: sorted({c["name"] for c in candidates})
               for retailer, candidates in by_retailer.items()
           },
       })
       resolved = {**state.get("resolved_choices", {}), item_name: answer}
       return {"resolved_choices": resolved, "pending_clarification_item": None}


   def route_after_resolve(state) -> str:
       return "resolve_ambiguity" if state.get("pending_clarification_item") else "build_shufersal_cart"
   ```
   `availability_by_retailer` is exactly the "Butter — Shufersal: Tnuva, Tara / Rami Levy:
   Tnuva, President" breakdown — informational only; the user still answers with one of
   `options`' ids (a label, resolved once and applied per retailer in `build_retailer_cart`,
   unchanged from before).
8. Write `app/agent/nodes/build_retailer_cart.py` — builds **one retailer's** complete cart
   from the resolved labels, independently of the other retailer (spec §4 step 8):
   ```python
   from app.agent.state import AgentState


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


   def make_build_retailer_cart(retailer: str, client):
       async def build_cart(state: AgentState) -> AgentState:
           parsed = state["parsed_request"]
           lines: list[dict] = []
           missing: list[dict] = []

           for item in parsed["items"]:
               name = item["name"]
               label = state["resolved_choices"].get(name, name)
               candidates = await client.search_product(label, retailer)
               if not candidates:
                   missing.append({"name": name, "reason": "not_found"})
                   continue

               best = min(candidates, key=lambda c: c["price"])
               price_info = await client.get_product_price(retailer, best["item_code"])
               lines.append({
                   "name": name,
                   "item_code": best["item_code"],
                   "product_name": best["name"],
                   "unit_price": price_info["unit_price"],
                   "qty": 1,
                   "subtotal": price_info["price"],
               })

           total = sum(line["subtotal"] for line in lines)
           budget = parsed.get("budget")
           over_budget_by = round(total - budget, 2) if budget is not None and total > budget else None

           trade_offs = []
           if over_budget_by is not None and lines:
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
               "over_budget_by": over_budget_by,
               "trade_off_suggestions": trade_offs,
           }
           return {"retailer_carts": {**state.get("retailer_carts", {}), retailer: cart}}

       return build_cart
   ```
   Dietary filtering (CP7) plugs into this function's candidate list, exactly like item
   resolution — see CP7's "Files to Modify" for `build_retailer_cart.py`. Note the
   `not_found` reason here means "no match in *this* retailer's catalog" — it says nothing
   about the other retailer, whose cart is built completely independently.
9. Write `app/agent/nodes/choose_retailer.py` — presents both carts and pauses; this
   **is** the approval gate for browser automation (CP8 extends past it):
   ```python
   from langgraph.types import interrupt


   async def choose_retailer(state):
       carts = state["retailer_carts"]
       shufersal, rami_levy = carts["shufersal"], carts["rami_levy"]
       diff = round(shufersal["total"] - rami_levy["total"], 2)

       answer = interrupt({
           "reason": "retailer_choice",
           "question": "Here are both carts — which would you like to use?",
           "carts": {
               "shufersal": {**shufersal, "savings_vs_other": max(-diff, 0)},
               "rami_levy": {**rami_levy, "savings_vs_other": max(diff, 0)},
           },
           "options": [
               {"id": "shufersal", "label": "Use Shufersal Online"},
               {"id": "rami_levy", "label": "Use Rami Levy Online"},
               {"id": "decline", "label": "Neither — just show me this"},
           ],
       })
       return {"chosen_retailer": answer if answer in ("shufersal", "rami_levy") else None}
   ```
10. Write `app/agent/nodes/finalize.py`:
    ```python
    def finalize(state):
        carts = state["retailer_carts"]
        warnings = []
        for retailer, cart in carts.items():
            if cart["missing_items"]:
                warnings.append({"code": "product_not_found", "retailer": retailer, "items": cart["missing_items"]})
            if cart["over_budget_by"] is not None:
                warnings.append({"code": "budget_exceeded", "retailer": retailer, "over_budget_by": cart["over_budget_by"]})

        return {
            "status": "partial_success" if warnings else "success",
            "warnings": warnings,
            "clarification": None,
            "final_result": {"carts": carts, "chosen_retailer": state.get("chosen_retailer")},
        }
    ```
11. Write `app/agent/checkpointer.py` (unchanged from prior design):
    ```python
    import os

    from langgraph.checkpoint.memory import MemorySaver


    def get_checkpointer():
        backend = os.environ.get("CHECKPOINTER_BACKEND", "memory")
        if backend == "memory":
            return MemorySaver()
        if backend == "sqlite":
            from langgraph.checkpoint.sqlite import SqliteSaver

            return SqliteSaver.from_conn_string(os.environ.get("CHECKPOINTER_SQLITE_PATH", "checkpoints.db"))
        raise ValueError(f"Unsupported CHECKPOINTER_BACKEND {backend!r} as of CP4 ('dynamodb' is added in CP11)")
    ```
12. Write `app/agent/graph.py`:
    ```python
    from langgraph.graph import END, START, StateGraph

    from app.agent.nodes.build_retailer_cart import make_build_retailer_cart
    from app.agent.nodes.choose_retailer import choose_retailer
    from app.agent.nodes.finalize import finalize
    from app.agent.nodes.parse_request import make_parse_request
    from app.agent.nodes.resolve_ambiguity import resolve_ambiguity, route_after_resolve
    from app.agent.nodes.resolve_items import make_resolve_items
    from app.agent.state import AgentState


    def build_graph(client, llm, checkpointer):
        graph = StateGraph(AgentState)
        graph.add_node("parse_request", make_parse_request(llm))
        graph.add_node("resolve_items", make_resolve_items(client))
        graph.add_node("resolve_ambiguity", resolve_ambiguity)
        graph.add_node("build_shufersal_cart", make_build_retailer_cart("shufersal", client))
        graph.add_node("build_rami_levy_cart", make_build_retailer_cart("rami_levy", client))
        graph.add_node("choose_retailer", choose_retailer)
        graph.add_node("finalize", finalize)

        graph.add_edge(START, "parse_request")
        graph.add_edge("parse_request", "resolve_items")
        graph.add_conditional_edges(
            "resolve_items", route_after_resolve, ["resolve_ambiguity", "build_shufersal_cart"]
        )
        graph.add_edge("resolve_ambiguity", "resolve_items")
        graph.add_edge("build_shufersal_cart", "build_rami_levy_cart")
        graph.add_edge("build_rami_levy_cart", "choose_retailer")
        graph.add_edge("choose_retailer", "finalize")
        graph.add_edge("finalize", END)

        return graph.compile(checkpointer=checkpointer)
    ```
    Carts are built sequentially (Shufersal then Rami Levy) for simplicity; parallelizing
    them (e.g. `asyncio.gather` via two branches) is a possible follow-up, not required.
13. Write the tests:
    - `test_graph_two_retailer_carts_happy_path.py`: fake client gives different
      candidates/prices per retailer for 2 items; assert both `retailer_carts` are built
      independently with correct totals; resume the `retailer_choice` interrupt with
      `"shufersal"`; assert `final_result["chosen_retailer"] == "shufersal"`.
    - `test_graph_ambiguous_item_interrupt.py`: fake client returns "Tnuva"/"Tara" for
      Shufersal and "Tnuva"/"President" for Rami Levy on the same query, none matching the
      item name exactly; assert the `ambiguous_product` interrupt's `options` is the deduped
      set (`Tnuva`, `Tara`, `President`) and `availability_by_retailer ==
      {"shufersal": ["Tara", "Tnuva"], "rami_levy": ["President", "Tnuva"]}`; resume with a
      chosen label; assert both retailer carts subsequently search using that label.
    - `test_graph_missing_item_one_retailer.py`: an item found at Shufersal but not Rami
      Levy; assert Shufersal's cart includes it and Rami Levy's cart reports it missing,
      with neither cart affected by the other.
    - `test_budget_trade_off_suggestion.py`: Rami Levy's cart exceeds budget; assert
      `trade_off_suggestions` has one entry with a cheaper alternative and positive
      `savings`; assert Shufersal (within budget) has none.
    - `test_choose_retailer_decline.py`: resume with `"decline"`; assert
      `chosen_retailer is None` and both carts are still present in `final_result`.
    - `test_resolve_item_rules.py`: unit tests for `_resolve_item` directly — single
      candidate, exact match, brand match, cheapest preference, and the
      still-ambiguous/no-preference case.
14. Run `pytest tests/agent -v`, iterate to green; `ruff check`; commit.

## Testing Tasks

- [ ] Two independent carts built correctly from fakes; happy path resumes with a choice.
- [ ] Ambiguous item → interrupt shows both the deduped selectable options and the
      per-retailer `availability_by_retailer` breakdown → resume → both carts use the
      resolution.
- [ ] Item missing at one retailer doesn't affect the other's cart.
- [ ] Budget trade-off suggestion generated only for the over-budget retailer.
- [ ] Decline → no retailer chosen, both carts still returned.
- [ ] `_resolve_item` unit tests for all auto-select rules and the still-ambiguous case.
- [ ] All tests run with fakes only — zero live network/Bedrock/MCP-process calls.

## Acceptance Criteria

Given fakes, the graph resolves items once (auto-selecting when unambiguous, or — when
asking — showing the user which retailer carries which option before they choose), builds
two independent retailer carts respecting budget/dietary/brand/price, and pauses for the
user to choose one or decline — matching spec §3, §4, and §8 exactly, with no recipe-path
code yet (CP7).

## Risks

- Sequential per-item `search_product` calls (both at resolution and per-retailer
  cart-building) are simple but not the fastest possible; parallelizing is a follow-up, not
  required for MVP correctness.
- The trade-off suggestion only targets the single most expensive item — good enough for an
  MVP demo; a more thorough search (trying combinations) is explicitly out of scope.
- With HTTP transport, running the real `McpSupermarketDataClient` locally requires the
  Supermarket-Data MCP server (CP3) to already be running as its own process on the
  expected port — unlike stdio, there's no auto-spawn. `make run`/docker-compose (CP9) must
  start it alongside the backend.

## Notes

CP5 wraps this graph behind FastAPI. CP7 adds the recipe branch ahead of `resolve_items` and
layers dietary filtering into `resolve_items`/`build_retailer_cart`; it must not change
`choose_retailer`/`finalize`'s shape. CP8 extends the graph past `choose_retailer` — if
`chosen_retailer` is set, invoke the Retailer-Cart MCP server for that retailer only, before
`finalize`; if not (decline), go straight to `finalize` as today.

## Definition of Done

- [ ] All nodes and the compiled graph exist and are wired as above.
- [ ] All six test files pass using fakes only; `ruff check` clean.
- [ ] Committed with message referencing CP4.
