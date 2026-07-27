# CP7 — Recipe Flow Integration & Dietary Rule Engine

Spec milestone: M2 (completes M2). Depends on: CP4, CP6.

## Goal

Add the recipe branch to the LangGraph agent — classify recipe vs. grocery-list requests,
select a recipe (with interrupt-on-ambiguity), fetch and scale its ingredients — and add the
deterministic dietary rule engine that enforces dietary constraints at both recipe-selection
and product-matching stages, per spec §4/§3.

## Scope

New graph nodes for the recipe path, a new `app/dietary` module, and the routing changes in
`app/agent/graph.py` that plug them in ahead of the existing (CP4) product-search path. The
grocery-list-only path from CP4 must continue to work unchanged when `request_type` is not
`"recipe"`.

## Deliverables

- A recipe request ("shakshuka for 4 people, no dairy") resolves to scaled ingredients,
  applies dietary filtering/substitution, and reaches the same `optimize_cart`/`finalize`
  nodes as the grocery-list path.
- Ambiguous recipe matches interrupt and resume correctly, mirroring CP4's product-match
  interrupt.
- A dietary-conflicting ingredient is substituted when a substitute exists, and reported as
  a `dietary_conflict` missing item when it doesn't — never silently dropped.

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
- `app/agent/nodes/search_products.py` — filter/substitute each item's candidates against
  dietary constraints *before* auto-resolving them (see step 8 below for why the ordering
  matters); `_resolve_candidate` itself is unchanged.
- `app/agent/nodes/optimize_cart.py` — distinguish `dietary_conflict` from `not_found` in
  the zero-candidate branch.
- `app/agent/mcp_clients.py` — add `McpRecipeClient` (mirrors `McpSupermarketDataClient`,
  targets CP6's server).
- `app/agent/graph.py` — wire the new nodes and the recipe-vs-grocery-list routing.
- `app/api/dependencies.py` — `build_graph` now also takes a recipe client.

## Detailed Implementation Steps

1. Write `app/dietary/rules.py` — the deterministic tagging + substitution engine (spec
   §3: "not left to LLM judgment"):
   ```python
   DIETARY_TAG_KEYWORDS = {
       "contains_dairy": ["milk", "cheese", "cream", "butter", "yogurt", "yoghurt"],
       "contains_gluten": ["wheat", "flour", "bread", "pasta", "barley"],
       "contains_meat": ["chicken", "beef", "pork", "lamb", "turkey"],
   }

   CONSTRAINT_TO_FORBIDDEN_TAGS = {
       "no dairy": {"contains_dairy"},
       "dairy free": {"contains_dairy"},
       "no gluten": {"contains_gluten"},
       "gluten free": {"contains_gluten"},
       "vegetarian": {"contains_meat"},
       "vegan": {"contains_meat", "contains_dairy"},
   }

   SUBSTITUTES = {
       "contains_dairy": {
           "milk": "oat milk",
           "cheese": "dairy-free cheese",
           "cream": "coconut cream",
           "butter": "margarine",
           "yogurt": "coconut yogurt",
       },
   }


   def tags_for_name(name: str) -> set[str]:
       lowered = name.lower()
       return {
           tag for tag, keywords in DIETARY_TAG_KEYWORDS.items() if any(k in lowered for k in keywords)
       }


   def forbidden_tags(constraints: list[str]) -> set[str]:
       forbidden: set[str] = set()
       for constraint in constraints:
           forbidden |= CONSTRAINT_TO_FORBIDDEN_TAGS.get(constraint.strip().lower(), set())
       return forbidden


   def violates(name: str, constraints: list[str]) -> bool:
       if not constraints:
           return False
       return bool(tags_for_name(name) & forbidden_tags(constraints))


   def find_substitute_query(name: str, forbidden: set[str]) -> str | None:
       lowered = name.lower()
       for tag in forbidden:
           for keyword, substitute in SUBSTITUTES.get(tag, {}).items():
               if keyword in lowered:
                   return substitute
       return None
   ```
2. Write `tests/dietary/test_rules.py`: `tags_for_name("Whole Milk 1L")` includes
   `"contains_dairy"`; `violates("Cheddar Cheese", ["no dairy"])` is `True`;
   `violates("Cheddar Cheese", [])` is `False`; `find_substitute_query("Whole Milk",
   {"contains_dairy"})` returns `"oat milk"`; a name/tag with no mapping returns `None`. Run,
   make green.
3. Extend `app/agent/nodes/parse_request.py`'s `ParsedRequestSchema` and `PARSE_PROMPT`:
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
   (`selection_preference` already existed on CP4's version of this schema — carry it
   forward unchanged here; it's not recipe-specific.) Update `PARSE_PROMPT` to instruct:
   classify `request_type`; if `"recipe"`, fill `recipe_query`/`servings` and leave `items`
   empty; if `"grocery_list"`, fill `items` and leave `recipe_query`/`servings` null. Update
   `make_parse_request`'s return dict to carry `request_type`, `recipe_query`, `servings`
   into `parsed_request`, keeping the existing `selection_preference` passthrough from CP4.
4. Add `McpRecipeClient` to `app/agent/mcp_clients.py`, structurally identical to
   `McpSupermarketDataClient` but targeting the CP6 server and its three tool names
   (`search_recipes`, `get_recipe`, `get_recipe_ingredients`), returning `.get("recipes")` /
   `.get("ingredients")` respectively from each tool's structured content.
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
       answer = interrupt(
           {
               "reason": "ambiguous_recipe",
               "question": "I found a few recipes — which one did you mean?",
               "options": [{"id": str(r["id"]), "label": r["title"]} for r in candidates],
           }
       )
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
           items = [{"name": ing["name"], "quantity": ing["amount"]} for ing in result["ingredients"]]
           updated_request = {**state["parsed_request"], "items": items}
           return {"parsed_request": updated_request}

       return get_recipe_ingredients
   ```
8. Modify `app/agent/nodes/search_products.py` to filter each item's candidates against
   forbidden tags, and substitute or flag, before resolving:
   ```python
   from app.dietary.rules import find_substitute_query, forbidden_tags, tags_for_name
   ```
   **Important ordering fix**: dietary filtering must happen *before* an item is
   auto-resolved, not after — otherwise CP4's `_resolve_candidate` could auto-select a
   dietary-violating candidate (e.g. the one exact-name match happens to be a dairy
   product) and populate `resolved_choices` before any dietary check ever ran, and a
   separate later filtering step would have no effect on an already-resolved item. So this
   is **not** a new standalone node — it's a modification to CP4's `make_search_products`
   itself, filtering/substituting each item's candidates *before* calling
   `_resolve_candidate` on them:
   ```python
   from app.dietary.rules import find_substitute_query, forbidden_tags, tags_for_name


   def make_search_products(client):
       async def search_products(state):
           parsed = state["parsed_request"]
           item_candidates = dict(state.get("item_candidates", {}))
           resolved_choices = dict(state.get("resolved_choices", {}))
           dietary_conflicts = list(state.get("dietary_conflicts", []))
           forbidden = forbidden_tags(parsed.get("dietary_constraints", []))
           ambiguous_item = None

           for item in parsed["items"]:
               name = item["name"]
               if name in resolved_choices:
                   continue
               if name not in item_candidates:
                   item_candidates[name] = await client.search_product(name)
               candidates = item_candidates[name]

               if forbidden:
                   compliant = [c for c in candidates if not (tags_for_name(c["name"]) & forbidden)]
                   if compliant:
                       candidates = compliant
                   else:
                       substitute_query = find_substitute_query(name, forbidden)
                       if substitute_query:
                           candidates = await client.search_product(substitute_query)
                       else:
                           candidates = []
                           if name not in dietary_conflicts:
                               dietary_conflicts.append(name)
                   item_candidates[name] = candidates

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
               "dietary_conflicts": dietary_conflicts,
               "pending_clarification_item": ambiguous_item,
           }

       return search_products
   ```
   When `dietary_constraints` is empty, `forbidden` is an empty set and the `if forbidden:`
   block never runs — this is exactly CP4's original behavior, unchanged for the
   grocery-list-only case. `_resolve_candidate` itself (CP4) is untouched.
9. Modify `app/agent/nodes/optimize_cart.py`'s zero-candidate branch to distinguish reason:
   ```python
   elif not candidates:
       reason = "dietary_conflict" if name in state.get("dietary_conflicts", []) else "not_found"
       missing_items.append({"name": name, "reason": reason})
       continue
   ```
10. Modify `app/agent/graph.py`: add the new recipe-path nodes; route `parse_request` to
    `search_recipes` when `request_type == "recipe"` and straight to `search_products`
    otherwise (unchanged CP4 path). Since dietary filtering now lives *inside*
    `search_products` (step 8), there is no separate dietary node to wire in — the
    `search_products → _route_after_search` edge from CP4 is unchanged:
    ```python
    def route_after_parse(state) -> str:
        return "search_recipes" if state["parsed_request"]["request_type"] == "recipe" else "search_products"


    def build_graph(supermarket_client, recipe_client, llm, checkpointer):
        graph = StateGraph(AgentState)
        graph.add_node("parse_request", make_parse_request(llm))
        graph.add_node("search_recipes", make_search_recipes(recipe_client))
        graph.add_node("resolve_recipe_ambiguity", resolve_recipe_ambiguity)
        graph.add_node("get_recipe_ingredients", make_get_recipe_ingredients(recipe_client))
        graph.add_node("search_products", make_search_products(supermarket_client))
        graph.add_node("resolve_ambiguity", resolve_ambiguity)
        graph.add_node("optimize_cart", make_optimize_cart(supermarket_client))
        graph.add_node("finalize", finalize)

        graph.add_edge(START, "parse_request")
        graph.add_conditional_edges("parse_request", route_after_parse, ["search_recipes", "search_products"])
        graph.add_conditional_edges(
            "search_recipes", route_after_search_recipes, ["resolve_recipe_ambiguity", "get_recipe_ingredients"]
        )
        graph.add_edge("resolve_recipe_ambiguity", "get_recipe_ingredients")
        graph.add_edge("get_recipe_ingredients", "search_products")
        graph.add_conditional_edges(
            "search_products", _route_after_search, ["resolve_ambiguity", "optimize_cart"]
        )
        graph.add_edge("resolve_ambiguity", "search_products")
        graph.add_edge("optimize_cart", "finalize")
        graph.add_edge("finalize", END)

        return graph.compile(checkpointer=checkpointer)
    ```
    (`_route_after_search` itself is unchanged from CP4 — it just now reads
    `pending_clarification_item` as produced by the dietary-aware `search_products` from
    step 8.)
11. Modify `app/api/dependencies.py`'s `get_agent_app` to construct an `McpRecipeClient`
    (pointed at `mcp_servers.recipe_mcp.server`) and pass it into `build_graph`.
12. Write `tests/agent/test_graph_recipe_happy_path.py`: fake recipe client returns one
    clear recipe match and fixed ingredients; fake supermarket client resolves all of them
    unambiguously; assert the graph reaches `finalize` with a populated cart derived from
    the recipe's ingredients.
13. Write `tests/agent/test_graph_recipe_ambiguous_interrupt.py`: fake recipe client returns
    two non-exact-matching recipes; assert the graph interrupts with `reason:
    "ambiguous_recipe"` and the expected options; resume with the chosen id using the same
    `thread_id`; assert it proceeds to ingredient fetch and finalize correctly.
14. Write `tests/agent/test_dietary_substitution_flow.py`: parsed request with
    `dietary_constraints: ["no dairy"]` and an ingredient `"milk"`; fake supermarket client
    returns only dairy-tagged candidates for `"milk"` but valid candidates for the
    substitute query `"oat milk"`; assert the final cart contains the substitute, not the
    original dairy item. A second test: same constraint, no substitute mapping exists for
    the conflicting ingredient (e.g. `"chicken stock"` under `"vegan"` with no matching
    keyword) — assert it lands in `missing_items` with `reason: "dietary_conflict"`.
15. Run `pytest tests/dietary tests/agent -v`, iterate to green; `ruff check`; commit.

## Testing Tasks

- [ ] Dietary rule engine unit tests (tagging, violation check, substitute lookup).
- [ ] Recipe happy path end-to-end (fakes only).
- [ ] Recipe ambiguity interrupt/resume end-to-end (fakes only).
- [ ] Dietary substitution success case and dietary-conflict-no-substitute case.
- [ ] Confirm CP4's grocery-list tests still pass unmodified (regression check).

## Acceptance Criteria

A recipe request resolves through recipe selection (with interrupt on ambiguity), ingredient
scaling, dietary substitution/flagging, and into the same single-retailer cart-building path
as CP4 — matching spec §4 exactly, with all dietary decisions made by the deterministic rule
engine, never the LLM.

## Risks

- The keyword-based tagging/substitution approach in `app/dietary/rules.py` is intentionally
  simple for MVP scope and will miss more subtle dietary conflicts (e.g. hidden dairy in a
  processed ingredient's name) — acceptable per spec §11 Risks; do not over-build this in
  CP7, revisit only if CP15 hardening surfaces concrete gaps.

## Notes

Do not let the LLM (`parse_request`) make dietary compliance decisions — it only extracts
the constraint text; `app/dietary/rules.py` is the sole authority on violations and
substitutions, per spec §3/§4.

Every ingredient `get_recipe_ingredients` returns becomes a plain item in
`parsed_request["items"]` (step 7) and is resolved by the same
`search_products`/`_resolve_candidate`/`resolve_ambiguity` logic as a directly-typed
grocery item — this checkpoint only adds a dietary-filtering step at the top of
`search_products` (step 8), it does not fork a separate resolution path. The same
auto-select rules (single candidate, brand match, cheapest preference) and the same
interrupt-and-ask behavior apply either way. Do not add a
second, recipe-specific product-resolution path here.

## Definition of Done

- [ ] All new nodes and dietary engine implemented and wired; CP4 grocery-list tests still
      pass unmodified.
- [ ] All new tests listed above pass; `ruff check` clean.
- [ ] Committed with message referencing CP7. **M2 milestone complete at this point.**
