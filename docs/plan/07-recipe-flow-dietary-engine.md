# CP7 — Recipe Flow Integration & Dietary Rule Engine

Spec milestone: M2 (completes M2). Depends on: CP4, CP6.

## Goal

Add the recipe branch — classify recipe vs. grocery-list requests, select a recipe (with
interrupt-on-ambiguity), fetch and scale its ingredients — and add the deterministic dietary
rule engine, applied both to the cross-retailer shortlist (`resolve_items`) and to each
retailer's own candidate pool (`build_retailer_cart`), per spec §3/§4.

## Scope

New graph nodes for the recipe path, a new `app/dietary` module, and routing changes in
`app/agent/graph.py` ahead of CP4's existing `resolve_items`. The grocery-list-only path must
keep working unchanged when `request_type != "recipe"`.

## Deliverables

- A recipe request ("shakshuka for 4, no dairy") resolves to scaled ingredients and reaches
  the same `resolve_items` → per-retailer cart building CP4 already built — not a separate
  path.
- Ambiguous recipe matches interrupt/resume, mirroring CP4's item-ambiguity interrupt.
- A dietary-conflicting ingredient is substituted where possible (per retailer where it
  matters), else reported with `reason: "dietary_conflict"` — never silently dropped.

## Files to Create

```
app/dietary/__init__.py
app/dietary/rules.py
app/agent/nodes/search_recipes.py
app/agent/nodes/resolve_recipe_ambiguity.py
app/agent/nodes/get_recipe_ingredients.py
tests/dietary/test_rules.py
tests/agent/test_graph_recipe_happy_path.py
tests/agent/test_graph_recipe_ambiguous_interrupt.py
tests/agent/test_dietary_substitution_flow.py
```

## Files to Modify

- `app/agent/nodes/parse_request.py` — extend the schema/prompt with `request_type`,
  `recipe_query`, `servings`.
- `app/agent/nodes/resolve_items.py` — filter the merged shortlist by dietary constraints
  before auto-resolving; substitute or flag when nothing compliant remains.
- `app/agent/nodes/build_retailer_cart.py` — filter that retailer's own candidates by
  dietary constraints; substitute, or report `dietary_conflict`, independently per retailer.
- `app/agent/mcp_clients.py` — add `McpRecipeClient`.
- `app/agent/graph.py` — wire the new nodes and recipe-vs-grocery-list routing.
- `app/api/dependencies.py` — `build_graph` now also takes a recipe client.

## Detailed Implementation Steps

1. Write `app/dietary/rules.py` — deterministic tagging + substitution, not LLM judgment:
   ```python
   DIETARY_TAG_KEYWORDS = {
       "contains_dairy": ["milk", "cheese", "cream", "butter", "yogurt", "yoghurt"],
       "contains_gluten": ["wheat", "flour", "bread", "pasta", "barley"],
       "contains_meat": ["chicken", "beef", "pork", "lamb", "turkey"],
   }
   CONSTRAINT_TO_FORBIDDEN_TAGS = {
       "no dairy": {"contains_dairy"}, "dairy free": {"contains_dairy"},
       "no gluten": {"contains_gluten"}, "gluten free": {"contains_gluten"},
       "vegetarian": {"contains_meat"}, "vegan": {"contains_meat", "contains_dairy"},
   }
   SUBSTITUTES = {
       "contains_dairy": {
           "milk": "oat milk", "cheese": "dairy-free cheese", "cream": "coconut cream",
           "butter": "margarine", "yogurt": "coconut yogurt",
       },
   }


   def tags_for_name(name: str) -> set[str]:
       lowered = name.lower()
       return {tag for tag, kws in DIETARY_TAG_KEYWORDS.items() if any(k in lowered for k in kws)}


   def forbidden_tags(constraints: list[str]) -> set[str]:
       forbidden: set[str] = set()
       for c in constraints:
           forbidden |= CONSTRAINT_TO_FORBIDDEN_TAGS.get(c.strip().lower(), set())
       return forbidden


   def violates(name: str, constraints: list[str]) -> bool:
       return bool(tags_for_name(name) & forbidden_tags(constraints)) if constraints else False


   def find_substitute_query(name: str, forbidden: set[str]) -> str | None:
       lowered = name.lower()
       for tag in forbidden:
           for keyword, substitute in SUBSTITUTES.get(tag, {}).items():
               if keyword in lowered:
                   return substitute
       return None
   ```
2. Write `tests/dietary/test_rules.py`: tagging, `violates`, `find_substitute_query` —
   including the empty-constraints and no-mapping cases.
3. Extend `parse_request.py`'s schema/prompt:
   ```python
   from typing import Literal


   class ParsedRequestSchema(BaseModel):
       request_type: Literal["recipe", "grocery_list"]
       items: list[str] = []
       recipe_query: str | None = None
       servings: int | None = None
       budget: float | None = None
       dietary_constraints: list[str] = []
       retailer_preference: str | None = None
       brand_preference: str | None = None
       selection_preference: Literal["cheapest", "no_preference"] = "no_preference"
   ```
   Update `PARSE_PROMPT`: classify `request_type`; if `"recipe"`, fill `recipe_query`/
   `servings`, leave `items` empty; if `"grocery_list"`, the reverse. Carry
   `selection_preference` through unchanged (it already existed on CP4's schema).
4. Add `McpRecipeClient` to `mcp_clients.py` — same HTTP pattern as
   `McpSupermarketDataClient` (`streamablehttp_client(base_url)`, CP4), targeting CP6's
   server (`search_recipes`, `get_recipe`, `get_recipe_ingredients`) at its own URL, e.g.
   `RECIPE_MCP_URL=http://localhost:8002/mcp` locally.
5. Write `app/agent/nodes/search_recipes.py`:
   ```python
   def make_search_recipes(recipe_client):
       async def search_recipes(state):
           query = state["parsed_request"]["recipe_query"]
           recipes = await recipe_client.search_recipes(query)
           ambiguous = len(recipes) > 1 and not any(
               r["title"].strip().lower() == query.strip().lower() for r in recipes
           )
           return {"recipe_candidates": recipes, "recipe_ambiguous": ambiguous}
       return search_recipes


   def route_after_search_recipes(state) -> str:
       return "resolve_recipe_ambiguity" if state.get("recipe_ambiguous") else "get_recipe_ingredients"
   ```
6. Write `app/agent/nodes/resolve_recipe_ambiguity.py`:
   ```python
   from langgraph.types import interrupt


   async def resolve_recipe_ambiguity(state):
       candidates = state["recipe_candidates"]
       answer = interrupt({
           "reason": "ambiguous_recipe",
           "question": "I found a few recipes — which one did you mean?",
           "options": [{"id": str(r["id"]), "label": r["title"]} for r in candidates],
       })
       chosen = next(r for r in candidates if str(r["id"]) == answer)
       return {"chosen_recipe_id": chosen["id"], "recipe_ambiguous": False}
   ```
7. Write `app/agent/nodes/get_recipe_ingredients.py`:
   ```python
   def make_get_recipe_ingredients(recipe_client):
       async def get_recipe_ingredients(state):
           recipe_id = state.get("chosen_recipe_id") or state["recipe_candidates"][0]["id"]
           servings = state["parsed_request"].get("servings")
           result = await recipe_client.get_recipe_ingredients(recipe_id, servings)
           items = [{"name": i["name"], "quantity": i["amount"]} for i in result["ingredients"]]
           return {"parsed_request": {**state["parsed_request"], "items": items}}
       return get_recipe_ingredients
   ```
8. Modify `resolve_items.py`'s `_candidates_by_retailer` to filter each retailer's own
   candidates by dietary constraints *before* they're grouped for display/dedup, and
   `resolve_items` to substitute or flag when nothing compliant remains anywhere:
   ```python
   from app.dietary.rules import find_substitute_query, forbidden_tags, tags_for_name


   async def _candidates_by_retailer(client, name: str, forbidden: set[str]) -> dict[str, list[dict]]:
       result = {}
       for retailer in RETAILERS:
           candidates = await client.search_product(name, retailer)
           if forbidden:
               candidates = [c for c in candidates if not (tags_for_name(c["name"]) & forbidden)]
           result[retailer] = candidates
       return result
   ```
   In `make_resolve_items`, compute `forbidden = forbidden_tags(parsed.get("dietary_constraints", []))`
   once per call, pass it into `_candidates_by_retailer(client, name, forbidden)`. If
   `_unique_labels(by_retailer)` comes back empty *because of filtering* (i.e. `forbidden` is
   non-empty), try `find_substitute_query(name, forbidden)`: if found, redo the per-retailer
   search on the substitute query (same filtering applied) and use that as `by_retailer`
   instead; if not, record `name` in a new `dietary_conflicts` state list instead of marking
   it ambiguous, and skip asking about it. This keeps the per-retailer breakdown
   (`availability_by_retailer` in `resolve_ambiguity.py`, CP4) dietary-compliant too — a
   filtered-out option never appears in what the user is shown.
9. Modify `build_retailer_cart.py` similarly — filter that retailer's own `search_product`
   results by `forbidden`, try the same substitute-query fallback for candidates missing at
   *this* retailer specifically, and set `"reason": "dietary_conflict"` (instead of
   `"not_found"`) on the missing-item entry when the item was filtered out for dietary
   reasons rather than genuinely absent:
   ```python
   candidates = await client.search_product(label, retailer)
   if forbidden:
       compliant = [c for c in candidates if not (tags_for_name(c["name"]) & forbidden)]
       if not compliant:
           sub_query = find_substitute_query(name, forbidden)
           compliant = await client.search_product(sub_query, retailer) if sub_query else []
       candidates = compliant
   if not candidates:
       reason = "dietary_conflict" if name in state.get("dietary_conflicts", []) else "not_found"
       missing.append({"name": name, "reason": reason})
       continue
   ```
10. Modify `graph.py`: add the recipe nodes ahead of `resolve_items`; route
    `parse_request` to `search_recipes` when `request_type == "recipe"`, else straight to
    `resolve_items` (unchanged CP4 path):
    ```python
    def route_after_parse(state) -> str:
        return "search_recipes" if state["parsed_request"]["request_type"] == "recipe" else "resolve_items"


    def build_graph(supermarket_client, recipe_client, llm, checkpointer):
        graph = StateGraph(AgentState)
        graph.add_node("parse_request", make_parse_request(llm))
        graph.add_node("search_recipes", make_search_recipes(recipe_client))
        graph.add_node("resolve_recipe_ambiguity", resolve_recipe_ambiguity)
        graph.add_node("get_recipe_ingredients", make_get_recipe_ingredients(recipe_client))
        graph.add_node("resolve_items", make_resolve_items(supermarket_client))
        graph.add_node("resolve_ambiguity", resolve_ambiguity)
        graph.add_node("build_shufersal_cart", make_build_retailer_cart("shufersal", supermarket_client))
        graph.add_node("build_rami_levy_cart", make_build_retailer_cart("rami_levy", supermarket_client))
        graph.add_node("choose_retailer", choose_retailer)
        graph.add_node("finalize", finalize)

        graph.add_edge(START, "parse_request")
        graph.add_conditional_edges("parse_request", route_after_parse, ["search_recipes", "resolve_items"])
        graph.add_conditional_edges(
            "search_recipes", route_after_search_recipes, ["resolve_recipe_ambiguity", "get_recipe_ingredients"]
        )
        graph.add_edge("resolve_recipe_ambiguity", "get_recipe_ingredients")
        graph.add_edge("get_recipe_ingredients", "resolve_items")
        graph.add_conditional_edges("resolve_items", route_after_resolve, ["resolve_ambiguity", "build_shufersal_cart"])
        graph.add_edge("resolve_ambiguity", "resolve_items")
        graph.add_edge("build_shufersal_cart", "build_rami_levy_cart")
        graph.add_edge("build_rami_levy_cart", "choose_retailer")
        graph.add_edge("choose_retailer", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(checkpointer=checkpointer)
    ```
11. Modify `app/api/dependencies.py`'s `get_agent_app` to construct an `McpRecipeClient(
    base_url=os.environ.get("RECIPE_MCP_URL", "http://localhost:8002/mcp"))` and pass it
    into `build_graph`. Like CP5's Supermarket-Data MCP server, CP6's Recipe MCP server must
    already be running for this to work locally.
12. Write `tests/agent/test_graph_recipe_happy_path.py` (recipe → scaled ingredients →
    both retailer carts built) and `test_graph_recipe_ambiguous_interrupt.py` (two recipe
    matches → interrupt → resume → proceeds).
13. Write `tests/agent/test_dietary_substitution_flow.py`: `dietary_constraints: ["no
    dairy"]`, ingredient `"milk"`; fake client returns only dairy candidates for `"milk"`
    but valid ones for `"oat milk"` — assert both retailer carts contain the substitute, not
    the original. A second case: no substitute mapping exists — assert `missing_items` shows
    `reason: "dietary_conflict"` at whichever retailer(s) lack a compliant option.
14. Run `pytest tests/dietary tests/agent -v`; confirm CP4's grocery-list tests still pass
    unmodified; `ruff check`; commit.

## Testing Tasks

- [ ] Dietary rule engine unit tests.
- [ ] Recipe happy path and ambiguity interrupt/resume (fakes only).
- [ ] Dietary substitution success case and no-substitute `dietary_conflict` case.
- [ ] CP4's grocery-list tests still pass unmodified (regression check).

## Acceptance Criteria

A recipe request resolves through recipe selection (interrupt on ambiguity), ingredient
scaling, and dietary-aware item resolution/cart-building — reaching the exact same
`resolve_items`/`build_retailer_cart`/`choose_retailer` path as a grocery list, with all
dietary decisions made by the deterministic rule engine, never the LLM.

## Risks

- The keyword-based tagging/substitution in `app/dietary/rules.py` is intentionally simple
  for MVP scope and will miss subtler conflicts (e.g. hidden dairy in a processed
  ingredient's name) — acceptable per spec §11; revisit only if CP15 hardening surfaces
  concrete gaps.

## Notes

The LLM (`parse_request`) only extracts constraint text — `app/dietary/rules.py` is the sole
authority on violations/substitutions, applied independently in the cross-retailer shortlist
and in each retailer's own cart-building, never once globally.

## Definition of Done

- [ ] All new nodes and dietary integration implemented; CP4 tests still pass unmodified.
- [ ] All new tests pass; `ruff check` clean.
- [ ] Committed with message referencing CP7. **M2 milestone complete at this point.**
