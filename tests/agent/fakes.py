from types import SimpleNamespace

from app.db.repositories import SEED_INGREDIENT_TRANSLATIONS, canonicalize_ingredient_name


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

    Also backs get_recipe_ingredients' persistent ingredient-translation cache (CP9
    follow-up) — seeded with the same small known-good set the real Supermarket-Data MCP
    seeds at startup (SEED_INGREDIENT_TRANSLATIONS), so recipe tests get realistic
    cache-hit behavior for common ingredients (tomatoes, milk, onion...) without needing
    a real DB or LLM call. Pass `seed_translations=False` for a test that specifically
    wants every ingredient to miss the cache (e.g. to exercise the LLM-fallback path).
    """

    def __init__(
        self,
        candidates: dict[tuple[str, str], list[dict]],
        prices: dict[tuple[str, str], dict],
        seed_translations: bool = True,
    ):
        self._candidates = candidates
        self._prices = prices
        self._translations: dict[str, str] = (
            dict(SEED_INGREDIENT_TRANSLATIONS) if seed_translations else {}
        )

    async def search_product(self, query: str, retailer: str) -> list[dict]:
        return self._candidates.get((query, retailer), [])

    async def get_product_price(self, retailer: str, item_code: str) -> dict | None:
        return self._prices.get((retailer, item_code))

    async def get_ingredient_translations(self, names: list[str]) -> dict[str, str]:
        canonical_by_name = {name: canonicalize_ingredient_name(name) for name in names}
        return {
            name: self._translations[canonical]
            for name, canonical in canonical_by_name.items()
            if canonical in self._translations
        }

    async def save_ingredient_translations(self, entries: list[dict]) -> None:
        for entry in entries:
            self._translations[canonicalize_ingredient_name(entry["name"])] = entry["search_name_he"]


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

    By default returns a canned `parsed` value (typically a ParsedRequestSchema)
    regardless of which schema was requested. Pass `parsed=None` with `raw_content` set
    (a string, or a Bedrock content-block list) to simulate the
    openai.gpt-oss-20b-1:0-on-Bedrock quirk where the model answers with plain JSON text
    instead of a real tool call — `with_structured_output` then has nothing to parse and
    returns `parsed=None`, which the caller (parse_request.py, ingredient_translation.py)
    must fall back on.

    `build_graph`'s single `llm` is shared by more than one structured-output call now
    (parse_request's ParsedRequestSchema, and get_recipe_ingredients' own
    IngredientTranslationSchema for never-before-seen ingredients) — pass
    `parsed_by_schema={SomeSchema: some_instance, ...}` when a graph-level test needs the
    fake to answer correctly for more than one schema in the same run; falls back to the
    single `parsed` value for any schema not in that mapping.
    """

    def __init__(self, parsed=None, raw_content=None, parsed_by_schema: dict | None = None):
        self._parsed = parsed
        self._raw_content = raw_content
        self._parsed_by_schema = parsed_by_schema or {}
        self._last_schema = None

    def with_structured_output(self, schema, include_raw=False):
        self._last_schema = schema
        return self

    async def ainvoke(self, messages) -> dict:
        parsed = self._parsed_by_schema.get(self._last_schema, self._parsed)
        return {
            "raw": SimpleNamespace(content=self._raw_content),
            "parsed": parsed,
            "parsing_error": None,
        }
