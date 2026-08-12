import logging
import os
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_servers.retailer_cart_mcp.adapters.rami_levy import RamiLevyAdapter
from mcp_servers.retailer_cart_mcp.adapters.shufersal import ShufersalAdapter
from mcp_servers.retailer_cart_mcp.automation import prepare_cart_for_retailer
from mcp_servers.retailer_cart_mcp.schemas import CartItemRequest, PrepareRetailerCartResponse

ADAPTERS = {"shufersal": ShufersalAdapter, "rami_levy": RamiLevyAdapter}
SESSIONS_DIR = os.environ.get("RETAILER_SESSIONS_DIR", "sessions")
logger = logging.getLogger(__name__)


def _log_resolved_session_file(retailer: str, session_path: str) -> None:
    # File path and metadata only — never cookie/localStorage contents. Exists to answer,
    # from the container's own logs, "which exact file on disk did this request actually
    # read" without ever needing to expose the session's secrets to check that.
    try:
        stat = os.stat(session_path)
    except FileNotFoundError:
        logger.info(
            "retailer_cart_mcp: session file for %s not found: path=%s", retailer, session_path
        )
        return
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    logger.info(
        "retailer_cart_mcp: resolved session file for %s: path=%s size_bytes=%d mtime_utc=%s",
        retailer,
        session_path,
        stat.st_size,
        mtime,
    )


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
    # FastMCP auto-enables DNS-rebinding protection restricted to localhost (captured at
    # construction time, before __main__ rebinds host to 0.0.0.0 below) — docker-compose
    # peers reach this server as "retailer-cart-mcp", and the Kubernetes Service peers
    # reach it through is named "retailer-cart-mcp-svc" (see
    # infra/k8s/*/retailer-cart-mcp/retailer-cart-mcp-service.yaml), a different hostname —
    # the localhost-only default would reject both with 421 Misdirected Request, so both
    # hostnames must be allowed explicitly.
    mcp = FastMCP(
        "retailer-cart",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                "127.0.0.1:*",
                "localhost:*",
                "[::1]:*",
                "retailer-cart-mcp:*",
                "retailer-cart-mcp-svc:*",
            ],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
        ),
    )

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

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
        _log_resolved_session_file(retailer, session_path)
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
