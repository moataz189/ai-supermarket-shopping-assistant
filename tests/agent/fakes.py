from app.agent.nodes.parse_request import ParsedRequestSchema


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
