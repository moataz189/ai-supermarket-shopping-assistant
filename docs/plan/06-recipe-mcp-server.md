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

## Detailed Implementation Steps

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
       mcp.run()
   ```
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

- [ ] `search_recipes` contract test.
- [ ] `get_recipe` contract test.
- [ ] `get_recipe_ingredients` scaling test (doubled servings → doubled amounts) and
      default-servings test.
- [ ] Confirm zero network calls occur when running this test file (e.g. by running with
      network access disabled/mocked at the socket level, or by code review confirming only
      `FakeSpoonacularClient` is used).

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

- [ ] All three tools implemented and contract-tested against fixtures.
- [ ] Scaling math verified exact.
- [ ] `ruff check` clean, tests green, committed referencing CP6.
