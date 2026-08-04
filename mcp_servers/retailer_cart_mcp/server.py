import os

from mcp.server.fastmcp import FastMCP

from mcp_servers.retailer_cart_mcp.adapters.rami_levy import RamiLevyAdapter
from mcp_servers.retailer_cart_mcp.adapters.shufersal import ShufersalAdapter
from mcp_servers.retailer_cart_mcp.automation import prepare_cart_for_retailer
from mcp_servers.retailer_cart_mcp.schemas import CartItemRequest, PrepareRetailerCartResponse

ADAPTERS = {"shufersal": ShufersalAdapter, "rami_levy": RamiLevyAdapter}
SESSIONS_DIR = os.environ.get("RETAILER_SESSIONS_DIR", "sessions")


def _refusal(
    retailer: str, items: list[CartItemRequest], item_reason: str, blocked_reason: str
) -> PrepareRetailerCartResponse:
    return PrepareRetailerCartResponse(
        retailer=retailer,
        added=[],
        failed=[
            {"name": i.name, "item_code": i.item_code, "status": "error", "reason": item_reason}
            for i in items
        ],
        blocked=True,
        blocked_reason=blocked_reason,
        cart_url=None,
    )


def create_server(adapters: dict = ADAPTERS, sessions_dir: str = SESSIONS_DIR) -> FastMCP:
    mcp = FastMCP("retailer-cart")

    @mcp.tool()
    async def prepare_retailer_cart(
        retailer: str, items: list[CartItemRequest]
    ) -> PrepareRetailerCartResponse:
        # No browser is ever launched for a retailer we don't have an adapter for, or one
        # with no captured login session — both checks happen before anything Playwright
        # related runs.
        adapter_factory = adapters.get(retailer)
        if adapter_factory is None:
            return _refusal(retailer, items, "unsupported_retailer", "unsupported_retailer")

        session_path = os.path.join(sessions_dir, f"{retailer}.json")
        if not os.path.exists(session_path):
            return _refusal(retailer, items, "no_login_session", "login_required")

        result = await prepare_cart_for_retailer(
            adapter_factory(), [i.model_dump() for i in items], storage_state_path=session_path
        )
        return PrepareRetailerCartResponse(**result)

    return mcp


mcp = create_server()

if __name__ == "__main__":
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.environ.get("PORT", "8003"))
    mcp.run(transport="streamable-http")
