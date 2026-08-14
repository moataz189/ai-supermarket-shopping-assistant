import re
from types import SimpleNamespace

# A small, test-scoped ingredient dictionary (english_name -> hebrew_search_term) for
# recipe-flow graph tests that need get_recipe_ingredients' translation to actually
# resolve — deliberately not the real ~3.4k-entry dictionary
# (app/agent/data/ingredient_hebrew_translations.csv), so these tests stay self-contained
# and don't silently change behavior if that file's content changes.
TEST_INGREDIENT_DICTIONARY: dict[str, str] = {
    "eggs": "ביצים",
    "tomatoes": "עגבניה",
}


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
                {
                    "name": i["name"],
                    "amount": i["amount"] * ratio,
                    "unit": i["unit"],
                    **({"original_amount": i["original_amount"] * ratio} if "original_amount" in i else {}),
                    **({"original_unit": i["original_unit"]} if "original_unit" in i else {}),
                }
                for i in recipe["ingredients"]
            ],
        }


class FakeSupermarketDataClient:
    """In-memory stand-in for McpSupermarketDataClient. Never makes network calls.

    `candidates` maps (query, retailer) -> list of candidate dicts.
    `prices` maps (retailer, item_code) -> price dict.
    """

    def __init__(
        self,
        candidates: dict[tuple[str, str], list[dict]],
        prices: dict[tuple[str, str], dict],
    ):
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
    include_raw=True).ainvoke(...)`'s `{"raw", "parsed", "parsing_error"}` return shape
    for parse_request.py's call site.

    Returns a canned `parsed` value (typically a ParsedRequestSchema) for parse_request's
    call. Pass `parsed=None` with `raw_content` set (a string, or a Bedrock content-block
    list) to simulate the openai.gpt-oss-20b-1:0-on-Bedrock quirk where the model answers
    with plain JSON text instead of a real tool call — `with_structured_output` then has
    nothing to parse and returns `parsed=None`, which the caller (parse_request.py) must
    fall back on.

    A *separate* call site, product_relevance.py's relevance classification, calls
    `ainvoke` directly (no `with_structured_output` at all — see that module's docstring:
    this model doesn't reliably make tool calls, so structured output silently failed to
    parse for nearly every real query; the real code now parses a plain-text answer
    instead). Detected here by the prompt's own distinguishing text ("Candidate product
    names:"), not by `with_structured_output`, since that call is never made for this
    call site and `self._schema` would otherwise just hold whatever parse_request.py last
    set it to. `relevant_names=None` (the default) means "no filtering configured" —
    every candidate name found in the prompt itself is echoed back as relevant, a no-op
    equivalent to filtering never having run, so existing tests that don't care about
    this call site need no changes at all. Pass `relevant_names=[...]` to test actual
    filtering, or `relevant_names=[]` to simulate the model finding nothing relevant.
    """

    def __init__(self, parsed=None, raw_content=None, relevant_names=None):
        self._parsed = parsed
        self._raw_content = raw_content
        self._relevant_names = relevant_names
        self._schema = None

    def with_structured_output(self, schema, include_raw=False):
        self._schema = schema
        return self

    async def ainvoke(self, messages):
        if len(messages) >= 2 and "Candidate product names:" in messages[-1][1]:
            if self._relevant_names is not None:
                names = self._relevant_names
            else:
                # No filtering configured — pass every candidate name mentioned in the
                # prompt straight through as relevant (see product_relevance.py's "- name"
                # line format), a no-op equivalent to filtering never having run.
                names = re.findall(r"^- (.+)$", messages[-1][1], re.MULTILINE)
            return SimpleNamespace(content="\n".join(names) if names else "NONE")
        return {
            "raw": SimpleNamespace(content=self._raw_content),
            "parsed": self._parsed,
            "parsing_error": None,
        }
