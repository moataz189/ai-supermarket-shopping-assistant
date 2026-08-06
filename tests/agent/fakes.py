from types import SimpleNamespace

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


class FakeRetailerCartClient:
    """In-memory stand-in for McpRetailerCartClient. Never launches a browser — just
    records each call and returns a canned result, so graph tests can assert *whether* and
    *with what* the Retailer-Cart MCP would have been invoked."""

    def __init__(self, result: dict):
        self._result = result
        self.calls: list[tuple[str, list[dict]]] = []

    async def prepare_retailer_cart(self, retailer: str, items: list[dict]) -> dict:
        self.calls.append((retailer, items))
        return self._result


class FakeLLM:
    """Stand-in for ChatBedrockConverse. Mimics `.with_structured_output(schema,
    include_raw=True).ainvoke(...)`'s `{"raw", "parsed", "parsing_error"}` return shape.

    By default returns a canned `parsed` ParsedRequestSchema regardless of input. Pass
    `parsed=None` with `raw_content` set (a string, or a Bedrock content-block list) to
    simulate the openai.gpt-oss-20b-1:0-on-Bedrock quirk where the model answers with
    plain JSON text instead of a real tool call — `with_structured_output` then has
    nothing to parse and returns `parsed=None`, which parse_request.py must fall back on.
    """

    def __init__(self, parsed: ParsedRequestSchema | None = None, raw_content=None):
        self._parsed = parsed
        self._raw_content = raw_content

    def with_structured_output(self, schema, include_raw=False):
        return self

    async def ainvoke(self, messages) -> dict:
        return {
            "raw": SimpleNamespace(content=self._raw_content),
            "parsed": self._parsed,
            "parsing_error": None,
        }
