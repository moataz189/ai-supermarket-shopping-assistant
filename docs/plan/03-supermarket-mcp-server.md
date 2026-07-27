# CP3 — Supermarket-Data MCP Server

Spec milestone: M1. Depends on: CP2.

## Goal

Build the Supermarket-Data MCP server: a data-access-only tool that searches **one
retailer's catalog at a time** and returns pricing/listing detail. No cross-retailer
comparison, no preference logic — that's the agent's job (CP4).

## Scope

The MCP server process, its two tools (search, price lookup), contract tests. No LangGraph
integration yet (CP4 wires it in).

## Deliverables

- An MCP server exposing `search_product(query, retailer)` and
  `get_product_price(retailer, item_code)`, both scoped to one named retailer per call.
- Contract tests validating each tool's shape independently of any agent.

## Files to Create

```
mcp_servers/supermarket_mcp/__init__.py
mcp_servers/supermarket_mcp/server.py
mcp_servers/supermarket_mcp/schemas.py
tests/mcp/test_supermarket_mcp_contract.py
```

## Detailed Implementation Steps

1. Write `mcp_servers/supermarket_mcp/schemas.py`:
   ```python
   from pydantic import BaseModel


   class ProductCandidate(BaseModel):
       item_code: str
       name: str
       price: float


   class SearchProductResponse(BaseModel):
       candidates: list[ProductCandidate]


   class ProductPriceResponse(BaseModel):
       retailer: str
       store_id: str
       item_code: str
       name: str
       price: float
       unit_price: float
       listed_in_feed: bool
       last_updated_at: str
       stale: bool
   ```
2. Write a failing contract test first, `tests/mcp/test_supermarket_mcp_contract.py`:
   seed a couple of known rows for **both** retailers via `RetailerProduct`/CP2; assert
   `search_product("milk", "shufersal")` returns only Shufersal candidates;
   `get_product_price("shufersal", <item_code>)` returns the expected `unit_price`.
3. Implement `mcp_servers/supermarket_mcp/server.py`:
   ```python
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
       mcp.settings.port = int(os.environ.get("PORT", 8001))
       mcp.run(transport="streamable-http")
   ```
   This server runs as its **own long-lived HTTP process** (not spawned per call) —
   `python -m mcp_servers.supermarket_mcp.server` starts it listening on `PORT` (default
   `8001`), and CP4's client (`McpSupermarketDataClient`) connects to it over HTTP, not
   stdio. Verify `mcp.settings.host`/`.port` and the `transport="streamable-http"` argument
   against the installed `mcp` SDK version — the exact config surface can shift between
   releases.
4. Add a test asserting Shufersal and Rami Levy can have independent `stale` values (one
   `True`, one `False`) for the same conversation.
5. Run `pytest tests/mcp -v`, `ruff check`, commit.

## Testing Tasks

- [ ] `search_product` only ever returns candidates for the requested retailer.
- [ ] `get_product_price` returns correct `unit_price`, `store_id` (`413`/`39`), and `stale`.
- [ ] Per-retailer `stale` values verified independent.

## Acceptance Criteria

The server starts standalone; both tools are schema-valid and strictly scoped to the
retailer passed in, against the CP2 fixture-seeded database.

## Risks

- MCP SDK version drift — pin `mcp` in `pyproject.toml`; CP6/CP8's servers use the same
  pinned version, since the HTTP transport setup (step 3) must match across all three.

## Notes (transport)

Contract tests (step 2) call `search_product`/`get_product_price` as plain Python
functions, not over HTTP — `@mcp.tool()` doesn't change how the underlying function is
called directly, so tests stay fast and transport-agnostic. Only CP4's actual agent-to-server
integration goes over HTTP.

## Notes

Keep this server "dumb": no cross-retailer comparison, no preference filtering, no
"best product" judgment. If a future change needs that here, it belongs in CP4 instead.

## Definition of Done

- [ ] Both tools implemented and contract-tested.
- [ ] `ruff check` clean, tests green, committed referencing CP3.
