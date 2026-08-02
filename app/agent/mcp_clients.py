from typing import Protocol

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class SupermarketDataClient(Protocol):
    async def search_product(self, query: str, retailer: str) -> list[dict]: ...
    async def get_product_price(self, retailer: str, item_code: str) -> dict | None: ...


class McpSupermarketDataClient:
    def __init__(self, base_url: str):
        self.base_url = base_url  # e.g. "http://supermarket-mcp:8001/mcp"

    async def _call(self, tool_name: str, arguments: dict) -> dict | None:
        async with (
            streamablehttp_client(self.base_url) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return result.structuredContent

    async def search_product(self, query: str, retailer: str) -> list[dict]:
        result = await self._call("search_product", {"query": query, "retailer": retailer})
        return (result or {}).get("candidates", [])

    async def get_product_price(self, retailer: str, item_code: str) -> dict | None:
        return await self._call("get_product_price", {"retailer": retailer, "item_code": item_code})
