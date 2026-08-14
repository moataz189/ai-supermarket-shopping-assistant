# Touch to trigger cd.yml's path-based rebuild and re-pin the prod manifest to a SHA
# that includes the search_candidates retrieval fix (the run that would have done this
# failed on the now-fixed ingestion-manifest bug before it reached the manifest-commit
# step).
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.db.models import RetailerFeedStatus
from app.db.repositories import ProductRepository, unit_price
from app.db.session import SessionLocal
from mcp_servers.supermarket_mcp.schemas import (
    ProductCandidate,
    ProductPriceResponse,
    SearchProductResponse,
)

# FastMCP auto-enables DNS-rebinding protection restricted to localhost (captured at
# construction time, before __main__ rebinds host to 0.0.0.0 below) — docker-compose peers
# reach this server as "supermarket-mcp", and the Kubernetes Service peers reach it through
# is named "supermarket-mcp-svc" (see infra/k8s/*/supermarket-mcp/supermarket-mcp-service.yaml),
# a different hostname — the localhost-only default would reject both with 421 Misdirected
# Request, so both hostnames must be allowed explicitly.
mcp = FastMCP(
    "supermarket-data",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
            "supermarket-mcp:*",
            "supermarket-mcp-svc:*",
        ],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
    ),
)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


@mcp.tool()
def search_product(query: str, retailer: str) -> SearchProductResponse:
    with SessionLocal() as session:
        repo = ProductRepository(session)
        candidates = repo.search_candidates(query, retailer)
        return SearchProductResponse(
            candidates=[
                ProductCandidate(item_code=p.item_code, name=p.name, price=p.price)
                for p in candidates
            ]
        )


@mcp.tool()
def get_product_price(retailer: str, item_code: str) -> ProductPriceResponse | None:
    with SessionLocal() as session:
        repo = ProductRepository(session)
        product = repo.get_product(retailer, item_code)
        if product is None:
            return None
        status = session.get(RetailerFeedStatus, retailer)
        return ProductPriceResponse(
            retailer=product.retailer,
            store_id=product.store_id,
            item_code=product.item_code,
            name=product.name,
            price=product.price,
            unit_price=unit_price(product.price, product.package_size, product.package_unit),
            package_size=product.package_size,
            package_unit=product.package_unit,
            listed_in_feed=product.listed_in_feed,
            last_updated_at=product.last_updated_at.isoformat(),
            stale=status.stale if status else False,
        )


if __name__ == "__main__":
    import os

    from app.db.session import init_db

    # This is the one service with direct SQLite access, so table creation is ensured
    # here, not in the backend. Idempotent — safe on every startup regardless of whether
    # the ingestion job's own init_db() has run yet. Deliberately not run at module
    # import time (only under __main__), so importing this module in tests never touches
    # a real DB file as a side effect.
    init_db()

    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.environ.get("PORT", "8001"))
    mcp.run(transport="streamable-http")
