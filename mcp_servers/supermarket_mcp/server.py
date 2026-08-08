from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.db.models import RetailerFeedStatus
from app.db.repositories import (
    IngredientTranslationRepository,
    ProductRepository,
    canonicalize_ingredient_name,
    unit_price,
)
from app.db.session import SessionLocal
from mcp_servers.supermarket_mcp.schemas import (
    GetIngredientTranslationsResponse,
    IngredientTranslationEntry,
    ProductCandidate,
    ProductPriceResponse,
    SearchProductResponse,
)

# FastMCP auto-enables DNS-rebinding protection restricted to localhost (captured at
# construction time, before __main__ rebinds host to 0.0.0.0 below) — docker-compose peers
# reach this server as "supermarket-mcp", which the localhost-only default would reject with
# 421 Misdirected Request, so that hostname must be allowed explicitly.
mcp = FastMCP(
    "supermarket-data",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", "supermarket-mcp:*"],
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
            listed_in_feed=product.listed_in_feed,
            last_updated_at=product.last_updated_at.isoformat(),
            stale=status.stale if status else False,
        )


@mcp.tool()
def get_ingredient_translations(names: list[str]) -> GetIngredientTranslationsResponse:
    """Persistent English-ingredient-name -> Hebrew-catalog-search-term cache (CP9
    follow-up, 2026-08-08) — lives here, not in the backend/agent, since this is the one
    service with direct SQLite access (app/api/Dockerfile deliberately excludes app/db
    from the backend image; the agent only ever reaches product/catalog data over MCP).
    Only names actually found in the cache appear in the response — a cache miss is
    simply absent, not an error, so the caller (get_recipe_ingredients.py) knows to fall
    back to the LLM for exactly those."""
    with SessionLocal() as session:
        repo = IngredientTranslationRepository(session)
        canonical_by_name = {name: canonicalize_ingredient_name(name) for name in names}
        cached = repo.get_many(list(set(canonical_by_name.values())))
        translations = {
            name: cached[canonical].search_name_he
            for name, canonical in canonical_by_name.items()
            if canonical in cached
        }
        return GetIngredientTranslationsResponse(translations=translations)


@mcp.tool()
def save_ingredient_translations(entries: list[IngredientTranslationEntry]) -> None:
    """Writes newly-LLM-translated ingredient names back to the persistent cache, so the
    LLM is never asked to translate the same ingredient twice (see
    get_ingredient_translations above). Safe to call with names already cached — checks
    for existing rows first (a concurrent request could have cached the same ingredient
    between this caller's own get_ingredient_translations call and this save), since
    IngredientTranslationRepository.save_many itself always inserts rather than
    upserting."""
    with SessionLocal() as session:
        repo = IngredientTranslationRepository(session)
        # First occurrence wins on a duplicate (canonicalized) name within the same
        # batch — `dict()` would silently keep the *last* one instead.
        canonical_by_entry: dict[str, IngredientTranslationEntry] = {}
        for entry in entries:
            canonical_by_entry.setdefault(canonicalize_ingredient_name(entry.name), entry)
        existing = repo.get_many(list(canonical_by_entry))
        new_entries = [
            (canonical, entry.name, entry.search_name_he)
            for canonical, entry in canonical_by_entry.items()
            if canonical not in existing
        ]
        repo.save_many(new_entries)


if __name__ == "__main__":
    import os

    from app.db.repositories import seed_ingredient_translations
    from app.db.session import init_db

    # This is the one service with direct SQLite access, so ingredient_translations'
    # table creation and seed data are ensured here, not in the backend. Idempotent —
    # safe on every startup regardless of whether the ingestion job's own init_db() has
    # run yet. Deliberately not run at module import time (only under __main__), so
    # importing this module in tests never touches a real DB file as a side effect.
    init_db()
    with SessionLocal() as _startup_session:
        seed_ingredient_translations(_startup_session)

    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.environ.get("PORT", "8001"))
    mcp.run(transport="streamable-http")
