from app.agent.nodes.parse_request import ParsedRequestSchema


class FakeRecipeClient:
    """In-memory stand-in for McpRecipeClient. Never makes network calls.

    `search_results` maps query -> list of {"id", "title"} candidate dicts.
    `recipes` maps recipe_id -> full recipe dict with "servings"/"extendedIngredients"-style
    "ingredients" (each with "name"/"amount"/"unit"), keyed by the *original* servings — this
    fake replicates CP6's scaling math (`amount * requested_servings / original_servings`) so
    graph tests don't need to special-case a real Spoonacular response shape.
    """

    def __init__(self, search_results: dict[str, list[dict]], recipes: dict[int, dict]):
        self._search_results = search_results
        self._recipes = recipes

    async def search_recipes(self, query: str) -> list[dict]:
        return self._search_results.get(query, [])

    async def get_recipe(self, recipe_id: int) -> dict | None:
        recipe = self._recipes.get(recipe_id)
        if recipe is None:
            return None
        return {"id": recipe_id, "title": recipe["title"], "servings": recipe["servings"]}

    async def get_recipe_ingredients(self, recipe_id: int, servings: int | None = None) -> dict | None:
        recipe = self._recipes.get(recipe_id)
        if recipe is None:
            return None
        original_servings = recipe["servings"]
        target_servings = original_servings if servings is None else servings
        ratio = target_servings / original_servings
        return {
            "recipe_id": recipe_id,
            "servings": target_servings,
            "ingredients": [
                {"name": i["name"], "amount": i["amount"] * ratio, "unit": i["unit"]}
                for i in recipe["ingredients"]
            ],
        }


class FakeSupermarketDataClient:
    """In-memory stand-in for McpSupermarketDataClient. Never makes network calls.

    `candidates` maps (query, retailer) -> list of candidate dicts.
    `prices` maps (retailer, item_code) -> price dict.
    """

    def __init__(self, candidates: dict[tuple[str, str], list[dict]], prices: dict[tuple[str, str], dict]):
        self._candidates = candidates
        self._prices = prices

    async def search_product(self, query: str, retailer: str) -> list[dict]:
        return self._candidates.get((query, retailer), [])

    async def get_product_price(self, retailer: str, item_code: str) -> dict | None:
        return self._prices.get((retailer, item_code))


class FakeLLM:
    """Stand-in for ChatBedrockConverse. Returns a canned ParsedRequestSchema regardless
    of input, mimicking the `.with_structured_output(...).ainvoke(...)` call chain."""

    def __init__(self, parsed: ParsedRequestSchema):
        self._parsed = parsed

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages) -> ParsedRequestSchema:
        return self._parsed
