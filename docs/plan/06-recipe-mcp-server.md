# CP6 — Recipe MCP Server

Spec milestone: M2 (starts). Depends on: CP1 (independent of CP2–CP5's data layer).

## Goal

Build the custom, domain-specific Recipe MCP server: `search_recipes`, `get_recipe`, and
`get_recipe_ingredients` (with serving-size scaling), wrapping the Spoonacular API, following
the same dependency-injected, contract-tested pattern as CP3's Supermarket-Data MCP server.

## Scope

The MCP server process and its three tools, a thin Spoonacular HTTP client, and contract
tests against recorded fixture responses — no live Spoonacular calls in automated tests
(global constraint).

## Deliverables

- An MCP server startable as its own process, exposing `search_recipes`, `get_recipe`,
  `get_recipe_ingredients`.
- `get_recipe_ingredients(recipe_id, servings=N)` correctly scales every ingredient amount
  by `N / recipe.servings`.

## Files to Create

```
mcp_servers/recipe_mcp/__init__.py
mcp_servers/recipe_mcp/schemas.py
mcp_servers/recipe_mcp/spoonacular_client.py
mcp_servers/recipe_mcp/server.py
tests/fixtures/spoonacular/search_shakshuka.json
tests/fixtures/spoonacular/recipe_12345.json
tests/mcp/fakes.py
tests/mcp/test_recipe_mcp_contract.py
```

## Files to Modify

- `requirements.txt` — add `httpx` (runtime dependency: `SpoonacularClient` uses it to call
  the Spoonacular API — this is separate from `httpx` potentially also being used by
  FastAPI's `TestClient` in tests, which the requirement here already covers).

## Detailed Implementation Steps

Before step 1, add `httpx` to `requirements.txt` if it isn't already there from an earlier
checkpoint.

1. Write `mcp_servers/recipe_mcp/schemas.py`:
   ```python
   from pydantic import BaseModel


   class RecipeSummary(BaseModel):
       id: int
       title: str


   class SearchRecipesResponse(BaseModel):
       recipes: list[RecipeSummary]


   class RecipeDetail(BaseModel):
       id: int
       title: str
       servings: int


   class Ingredient(BaseModel):
       name: str
       amount: float
       unit: str


   class GetRecipeIngredientsResponse(BaseModel):
       recipe_id: int
       servings: int
       ingredients: list[Ingredient]
   ```
2. Write `mcp_servers/recipe_mcp/spoonacular_client.py`:
   ```python
   import os

   import httpx

   BASE_URL = "https://api.spoonacular.com"


   class SpoonacularClient:
       def __init__(self, api_key: str | None = None, client: httpx.Client | None = None):
           self.api_key = api_key or os.environ["SPOONACULAR_API_KEY"]
           self.client = client or httpx.Client(base_url=BASE_URL, timeout=10.0)

       def search_recipes(self, query: str, number: int = 5) -> list[dict]:
           response = self.client.get(
               "/recipes/complexSearch",
               params={"query": query, "number": number, "apiKey": self.api_key},
           )
           response.raise_for_status()
           return response.json()["results"]

       def get_recipe(self, recipe_id: int) -> dict:
           response = self.client.get(
               f"/recipes/{recipe_id}/information", params={"apiKey": self.api_key}
           )
           response.raise_for_status()
           return response.json()
   ```
3. Save two small, real-shaped fixture files by making one real Spoonacular call each
   (manually, during development, not in CI) and trimming the JSON to a few fields:
   `tests/fixtures/spoonacular/search_shakshuka.json` (a `complexSearch`-shaped response with
   2+ results) and `recipe_12345.json` (a `/information`-shaped response with `servings` and
   `extendedIngredients`, each with `name`/`amount`/`unit`).
4. Write `tests/mcp/fakes.py` with `FakeSpoonacularClient` that loads those fixture files and
   implements the same two methods as `SpoonacularClient`, so tests never hit the network.
5. Write `mcp_servers/recipe_mcp/server.py` as a factory (mirrors CP3's DI pattern):
   ```python
   from mcp.server.fastmcp import FastMCP

   from mcp_servers.recipe_mcp.schemas import (
       GetRecipeIngredientsResponse,
       Ingredient,
       RecipeDetail,
       RecipeSummary,
       SearchRecipesResponse,
   )
   from mcp_servers.recipe_mcp.spoonacular_client import SpoonacularClient


   def create_server(client) -> FastMCP:
       mcp = FastMCP("recipe")

       @mcp.tool()
       def search_recipes(query: str) -> SearchRecipesResponse:
           results = client.search_recipes(query)
           return SearchRecipesResponse(
               recipes=[RecipeSummary(id=r["id"], title=r["title"]) for r in results]
           )

       @mcp.tool()
       def get_recipe(recipe_id: int) -> RecipeDetail:
           data = client.get_recipe(recipe_id)
           return RecipeDetail(id=data["id"], title=data["title"], servings=data["servings"])

       @mcp.tool()
       def get_recipe_ingredients(
           recipe_id: int, servings: int | None = None
       ) -> GetRecipeIngredientsResponse:
           data = client.get_recipe(recipe_id)
           original_servings = data["servings"]
           target_servings = servings or original_servings
           ratio = target_servings / original_servings if original_servings else 1.0

           ingredients = [
               Ingredient(name=i["name"], amount=i["amount"] * ratio, unit=i["unit"])
               for i in data["extendedIngredients"]
           ]
           return GetRecipeIngredientsResponse(
               recipe_id=recipe_id, servings=target_servings, ingredients=ingredients
           )

       return mcp


   mcp = create_server(SpoonacularClient())

   if __name__ == "__main__":
       import os

       mcp.settings.host = "0.0.0.0"
       mcp.settings.port = int(os.environ.get("PORT", 8002))
       mcp.run(transport="streamable-http")
   ```
   Like CP3's server, this runs as its own long-lived HTTP process (`PORT`, default
   `8002`) — CP7's `McpRecipeClient` connects over HTTP, not stdio.
6. Write `tests/mcp/test_recipe_mcp_contract.py` building the server via
   `create_server(FakeSpoonacularClient())`:
   - `test_search_recipes_returns_candidates` — asserts `recipes` is non-empty and each item
     has `id`/`title`.
   - `test_get_recipe_returns_servings` — asserts the fixture's known `servings` value.
   - `test_get_recipe_ingredients_scales_amounts` — call with `servings=` double the
     fixture's original servings, assert every ingredient's `amount` is exactly double the
     original fixture value (exact ratio math, not approximate).
   - `test_get_recipe_ingredients_defaults_to_original_servings` — call with `servings=None`,
     assert amounts match the fixture unscaled.
7. Run `pytest tests/mcp/test_recipe_mcp_contract.py -v`, iterate to green; `ruff check`;
   commit.

## Testing Tasks

- [x] `search_recipes` contract test.
- [x] `get_recipe` contract test.
- [x] `get_recipe_ingredients` scaling test (doubled servings → doubled amounts) and
      default-servings test.
- [x] Confirm zero network calls occur when running this test file (e.g. by running with
      network access disabled/mocked at the socket level, or by code review confirming only
      `FakeSpoonacularClient` is used). Enforced at runtime via an autouse fixture that
      monkeypatches `httpx.Client.send` to raise if invoked, in addition to only ever
      constructing `FakeSpoonacularClient` in tests.
- [x] Additional (beyond the plan's minimum): contract tests for rejecting non-positive
      `servings` and non-positive `original_servings`, per the servings-validation
      improvement requested alongside this checkpoint.

## Acceptance Criteria

The Recipe MCP server can be started standalone; all three tools produce schema-valid
responses against fixture data; ingredient scaling math is exact for a known
servings-doubling case.

## Risks

- Spoonacular's actual response schema may include fields/edge cases (e.g. missing `amount`
  or non-numeric units) not captured by the two trimmed fixtures — track as a hardening item
  for CP15 rather than blocking this checkpoint.

## Notes

CP7 wires this server into the LangGraph agent's recipe branch and adds the
recipe-selection-ambiguity interrupt on top of `search_recipes`'s output — no changes to this
server should be needed for that.

## Definition of Done

- [x] All three tools implemented and contract-tested against fixtures.
- [x] Scaling math verified (via `pytest.approx()` rather than exact float equality — see
      "Deviations from the plan" below).
- [x] `ruff check` clean, tests green, committed referencing CP6.

### Deviations from the plan (intentional, requested by the implementation brief)

- **Lazy Spoonacular initialization**: `mcp_servers/recipe_mcp/server.py` no longer
  instantiates `SpoonacularClient` at module import time (no `mcp = create_server(SpoonacularClient())`
  at module scope). The real client is only constructed inside `if __name__ == "__main__":`,
  so importing `server.py` never requires `SPOONACULAR_API_KEY` and never opens an HTTP
  client or touches the network. `create_server(FakeSpoonacularClient())` works with zero
  environment variables set.
- **Servings validation**: `get_recipe_ingredients` uses
  `original_servings if servings is None else servings` (not `servings or original_servings`,
  which would incorrectly treat `servings=0` as "use the default"). Both `servings <= 0` and
  `original_servings <= 0` raise an explicit `ValueError` (surfaced to MCP clients as
  `ToolError`) instead of silently falling back to a `1.0` ratio.
- **Floating-point assertions**: the scaling contract test uses `pytest.approx()` instead of
  exact equality, since float multiplication is not guaranteed to be bit-exact.
- **Fixture-driven IDs**: `tests/mcp/fakes.py`'s `FakeSpoonacularClient` indexes recipes by
  the `id` field read from the fixture JSON (not a hardcoded literal), and the contract tests
  read the fixture's `id`/`servings`/`extendedIngredients` directly rather than hardcoding
  `12345` anywhere. (The fixture *filename* is `recipe_12345.json` per the plan's file list;
  the `id` inside it is `654959`, matching the search fixture — this is deliberate, so nothing
  in the implementation or tests can rely on the filename's number.)
- **HTTP client hygiene**: `SpoonacularClient` reuses a single `httpx.Client` (constructed
  once, injected or lazily created), calls `raise_for_status()` on every request, and has an
  explicit `timeout` configured.
- **No translation/normalization**: `search_recipes(query)` forwards the query to Spoonacular
  as-is; no language translation or normalization is performed in CP6 (deferred to CP7, which
  owns query normalization before calling this tool).

No scope was dropped from the original plan; the above are additive/corrective refinements
requested alongside the checkpoint. The only item explicitly deferred (per the plan's own
"Risks" section, not by this implementation) is hardening against additional Spoonacular
response edge cases (missing `amount`, non-numeric units), tracked for CP15.
