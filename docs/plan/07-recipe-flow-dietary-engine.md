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
app/agent/nodes/apply_dietary_constraints.py
tests/dietary/test_rules.py
tests/agent/test_graph_recipe_happy_path.py
tests/agent/test_graph_recipe_ambiguous_interrupt.py
tests/agent/test_dietary_substitution_flow.py
```

## Files to Modify

- `app/agent/nodes/parse_request.py` — extend the schema/prompt with `request_type`,
  `recipe_query`, `servings`.
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
   ```
   Update `PARSE_PROMPT` to instruct: classify `request_type`; if `"recipe"`, fill
   `recipe_query`/`servings` and leave `items` empty; if `"grocery_list"`, fill `items` and
   leave `recipe_query`/`servings` null. Update `make_parse_request`'s return dict to carry
   `request_type`, `recipe_query`, `servings` into `parsed_request`.
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
8. Write `app/agent/nodes/apply_dietary_constraints.py` — runs after `search_products`,
   filters each item's candidates against forbidden tags, and substitutes or flags:
   ```python
   from app.dietary.rules import find_substitute_query, forbidden_tags, tags_for_name


   def make_apply_dietary_constraints(client):
       async def apply_dietary_constraints(state):
           constraints = state["parsed_request"].get("dietary_constraints", [])
           forbidden = forbidden_tags(constraints)
           if not forbidden:
               return {}

           item_candidates = dict(state.get("item_candidates", {}))
           dietary_conflicts = list(state.get("dietary_conflicts", []))

           for item in state["parsed_request"]["items"]:
               name = item["name"]
               candidates = item_candidates.get(name, [])
               compliant = [c for c in candidates if not (tags_for_name(c["name"]) & forbidden)]
               if compliant:
                   item_candidates[name] = compliant
                   continue

               substitute_query = find_substitute_query(name, forbidden)
               if substitute_query:
                   item_candidates[name] = await client.search_product(substitute_query)
               else:
                   item_candidates[name] = []
                   if name not in dietary_conflicts:
                       dietary_conflicts.append(name)

           return {"item_candidates": item_candidates, "dietary_conflicts": dietary_conflicts}

       return apply_dietary_constraints
   ```
9. Modify `app/agent/nodes/optimize_cart.py`'s zero-candidate branch to distinguish reason:
   ```python
   elif not candidates:
       reason = "dietary_conflict" if name in state.get("dietary_conflicts", []) else "not_found"
       missing_items.append({"name": name, "reason": reason})
       continue
   ```
10. Modify `app/agent/graph.py`: add the new nodes; route `parse_request` to
    `search_recipes` when `request_type == "recipe"` and straight to `search_products`
    otherwise (unchanged CP4 path); insert `apply_dietary_constraints` between
    `search_products` and the ambiguity-routing conditional:
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
        graph.add_node("apply_dietary_constraints", make_apply_dietary_constraints(supermarket_client))
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
        graph.add_edge("search_products", "apply_dietary_constraints")
        graph.add_conditional_edges(
            "apply_dietary_constraints", _route_after_search, ["resolve_ambiguity", "optimize_cart"]
        )
        graph.add_edge("resolve_ambiguity", "search_products")
        graph.add_edge("optimize_cart", "finalize")
        graph.add_edge("finalize", END)

        return graph.compile(checkpointer=checkpointer)
    ```
    (`_route_after_search` now reads state produced by `apply_dietary_constraints`, unchanged
    from CP4.)
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
  CP7, revisit only if CP14 hardening surfaces concrete gaps.

## Notes

Do not let the LLM (`parse_request`) make dietary compliance decisions — it only extracts
the constraint text; `app/dietary/rules.py` is the sole authority on violations and
substitutions, per spec §3/§4.

## Definition of Done

- [ ] All new nodes and dietary engine implemented and wired; CP4 grocery-list tests still
      pass unmodified.
- [ ] All new tests listed above pass; `ruff check` clean.
- [ ] Committed with message referencing CP7. **M2 milestone complete at this point.**
