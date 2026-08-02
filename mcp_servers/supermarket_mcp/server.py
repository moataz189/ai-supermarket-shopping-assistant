from mcp.server.fastmcp import FastMCP

from app.db.models import RetailerFeedStatus
from app.db.repositories import ProductRepository, unit_price
from app.db.session import SessionLocal
from mcp_servers.supermarket_mcp.schemas import (
    ProductCandidate,
    ProductPriceResponse,
    SearchProductResponse,
)

mcp = FastMCP("supermarket-data")


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
            listed_in_feed=product.listed_in_feed,
            last_updated_at=product.last_updated_at.isoformat(),
            stale=status.stale if status else False,
        )


if __name__ == "__main__":
    import os

    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.environ.get("PORT", "8001"))
    mcp.run(transport="streamable-http")
