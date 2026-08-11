from typing import Protocol

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.metrics import mcp_call_total


class SupermarketDataClient(Protocol):
    async def search_product(self, query: str, retailer: str) -> list[dict]: ...
    async def get_product_price(self, retailer: str, item_code: str) -> dict | None: ...


class McpSupermarketDataClient:
    def __init__(self, base_url: str):
        self.base_url = base_url  # e.g. "http://supermarket-mcp:8001/mcp"

    async def _call(self, tool_name: str, arguments: dict) -> dict | None:
        try:
            async with (
                streamablehttp_client(self.base_url) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
        except Exception:
            mcp_call_total.labels(mcp_service="supermarket", status="error").inc()
            raise
        mcp_call_total.labels(mcp_service="supermarket", status="success").inc()
        return result.structuredContent

    async def search_product(self, query: str, retailer: str) -> list[dict]:
        result = await self._call("search_product", {"query": query, "retailer": retailer})
        return (result or {}).get("candidates", [])

    async def get_product_price(self, retailer: str, item_code: str) -> dict | None:
        # `get_product_price`'s tool signature returns `ProductPriceResponse | None`; FastMCP
        # can't emit a top-level object schema for a union, so it wraps the result under a
        # "result" key in `structuredContent` — unlike `search_product`'s plain
        # `SearchProductResponse`, which comes back unwrapped (see `search_product` above).
        result = await self._call("get_product_price", {"retailer": retailer, "item_code": item_code})
        return (result or {}).get("result")


class RecipeClient(Protocol):
    async def search_recipes(self, query: str) -> list[dict]: ...
    async def get_recipe(self, recipe_id: int) -> dict | None: ...
    async def get_recipe_ingredients(self, recipe_id: int, servings: int | None = None) -> dict | None: ...


class McpRecipeClient:
    def __init__(self, base_url: str):
        self.base_url = base_url  # e.g. "http://recipe-mcp:8002/mcp"

    async def _call(self, tool_name: str, arguments: dict) -> dict | None:
        try:
            async with (
                streamablehttp_client(self.base_url) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
        except Exception:
            mcp_call_total.labels(mcp_service="recipe", status="error").inc()
            raise
        mcp_call_total.labels(mcp_service="recipe", status="success").inc()
        return result.structuredContent

    async def search_recipes(self, query: str) -> list[dict]:
        result = await self._call("search_recipes", {"query": query})
        return (result or {}).get("recipes", [])

    async def get_recipe(self, recipe_id: int) -> dict | None:
        # `get_recipe` returns a plain `RecipeDetail` (no union), so — like
        # `search_product` above — it comes back unwrapped in `structuredContent`.
        return await self._call("get_recipe", {"recipe_id": recipe_id})

    async def get_recipe_ingredients(self, recipe_id: int, servings: int | None = None) -> dict | None:
        return await self._call(
            "get_recipe_ingredients", {"recipe_id": recipe_id, "servings": servings}
        )


class RetailerCartClient(Protocol):
    async def prepare_retailer_cart(self, retailer: str, items: list[dict]) -> dict: ...


class McpRetailerCartClient:
    def __init__(self, base_url: str):
        self.base_url = base_url  # e.g. "http://retailer-cart-mcp:8003/mcp"

    async def _call(self, tool_name: str, arguments: dict) -> dict | None:
        try:
            async with (
                streamablehttp_client(self.base_url) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
        except Exception:
            mcp_call_total.labels(mcp_service="retailer_cart", status="error").inc()
            raise
        mcp_call_total.labels(mcp_service="retailer_cart", status="success").inc()
        return result.structuredContent

    async def prepare_retailer_cart(self, retailer: str, items: list[dict]) -> dict:
        # `prepare_retailer_cart` returns a plain `PrepareRetailerCartResponse` (no union),
        # so — like `get_recipe` — it comes back unwrapped in `structuredContent`.
        return await self._call("prepare_retailer_cart", {"retailer": retailer, "items": items})
