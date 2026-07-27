# CP3 — Supermarket-Data MCP Server

Spec milestone: M1. Depends on: CP2.

## Goal

Build the custom, domain-specific Supermarket-Data MCP server: a data-access-only tool that
searches candidate products and returns per-retailer offer detail, backed by the
`ProductRepository` from CP2. It must not contain shopping intelligence (that stays in the
agent, CP4).

## Scope

The MCP server process, its three tools (search, offer lookup, compare), MCP contract tests.
No LangGraph integration yet (CP4 wires it in as a tool-calling client).

## Deliverables

- An MCP server startable as its own process, exposing `search_product`,
  `get_product_offers`, `compare_product`.
- Contract tests validating each tool's request/response shape independently of any agent.

## Files to Create

```
mcp_servers/supermarket_mcp/__init__.py
mcp_servers/supermarket_mcp/server.py
mcp_servers/supermarket_mcp/schemas.py
tests/mcp/test_supermarket_mcp_contract.py
```

## Detailed Implementation Steps

1. Write `mcp_servers/supermarket_mcp/schemas.py` — the tool I/O contracts as Pydantic
   models:
   ```python
   from pydantic import BaseModel


   class ProductCandidate(BaseModel):
       product_id: str
       name: str
       basic_price: float | None = None


   class SearchProductRequest(BaseModel):
       query: str
       retailer: str | None = None


   class SearchProductResponse(BaseModel):
       candidates: list[ProductCandidate]


   class RetailerOfferView(BaseModel):
       retailer: str
       store_id: str
       item_code: str
       price: float
       unit_price: float
       listed_in_feed: bool
       last_updated_at: str
       stale: bool


   class GetProductOffersRequest(BaseModel):
       product_id: str


   class GetProductOffersResponse(BaseModel):
       product_id: str
       offers: list[RetailerOfferView]
   ```
2. Write a failing contract test first, `tests/mcp/test_supermarket_mcp_contract.py`,
   asserting: `search_product({"query": "milk"})` returns a `SearchProductResponse`-shaped
   payload with at least a `candidates` list of `product_id`/`name`; `get_product_offers`
   returns one entry per retailer with `unit_price` present. Seed the test database with a
   couple of known rows via `ProductRepository`/CP2 models before asserting.
3. Implement `mcp_servers/supermarket_mcp/server.py` using the MCP Python SDK, wiring each
   tool to `ProductRepository` (imported from `app.db.repositories`) and the CP2
   `unit_price` helper and `RetailerFeedStatus.stale` flag:
   ```python
   from mcp.server.fastmcp import FastMCP

   from app.db.repositories import ProductRepository, unit_price
   from app.db.session import SessionLocal
   from mcp_servers.supermarket_mcp.schemas import (
       GetProductOffersResponse,
       ProductCandidate,
       RetailerOfferView,
       SearchProductResponse,
   )

   mcp = FastMCP("supermarket-data")


   @mcp.tool()
   def search_product(query: str, retailer: str | None = None) -> SearchProductResponse:
       with SessionLocal() as session:
           repo = ProductRepository(session)
           candidates = repo.search_candidates(query)
           return SearchProductResponse(
               candidates=[
                   ProductCandidate(product_id=p.product_id, name=p.name)
                   for p in candidates
               ]
           )


   @mcp.tool()
   def get_product_offers(product_id: str) -> GetProductOffersResponse:
       with SessionLocal() as session:
           repo = ProductRepository(session)
           product = session.get(CanonicalProduct, product_id)
           by_retailer = repo.get_offers_by_retailer(product_id)
           statuses = {
               status.retailer: status
               for status in session.query(RetailerFeedStatus).all()
           }
           offers = [
               RetailerOfferView(
                   retailer=retailer,
                   store_id=offer.store_id,
                   item_code=offer.item_code,
                   price=offer.price,
                   unit_price=unit_price(offer.price, product.package_size, product.package_unit),
                   listed_in_feed=offer.listed_in_feed,
                   last_updated_at=offer.last_updated_at.isoformat(),
                   stale=statuses[retailer].stale if retailer in statuses else False,
               )
               for retailer, offer in by_retailer.items()
           ]
           return GetProductOffersResponse(product_id=product_id, offers=offers)


   @mcp.tool()
   def compare_product(candidate_ids: list[str]) -> GetProductOffersResponse:
       raise NotImplementedError  # implemented in step 5


   if __name__ == "__main__":
       mcp.run()
   ```
   Add `CanonicalProduct` and `RetailerFeedStatus` to the `app.db.models` import at the top
   of the file. The `if __name__ == "__main__":` block is required — `McpSupermarketDataClient`
   (CP4) spawns this server via `python -m mcp_servers.supermarket_mcp.server`, which only
   starts the MCP server if this entrypoint exists.
4. Confirm `stale` is wired correctly: each retailer's staleness comes from its own
   `RetailerFeedStatus` row per the per-retailer freshness rule from `docs/spec.md` §5 (each
   retailer's staleness is independent — do not collapse to one global flag). Add a test
   case in the contract test asserting one retailer can be `stale=True` while the other is
   `stale=False`.
5. Implement `compare_product(candidate_ids)`: call `get_product_offers` for each id and
   return the combined list — a thin wrapper, no additional scoring logic (scoring lives in
   the agent, CP4). Add a contract test for it.
6. Run `pytest tests/mcp -v`, fix until green; run `ruff check`; commit.

## Testing Tasks

- [ ] `search_product` returns lightweight candidates matching a fixture query.
- [ ] `get_product_offers` returns one offer per retailer with correct `unit_price`,
      `item_code`, and `store_id` (`413` for `shufersal`, `39` for `rami_levy`).
- [ ] Per-retailer `stale` flags are independent (one stale, one fresh, in the same
      response).
- [ ] `compare_product` returns combined offers for multiple candidate ids.

## Acceptance Criteria

The MCP server can be started standalone and its three tools produce schema-valid responses
against the CP2 fixture-seeded database, without importing or depending on any agent code.

## Risks

- MCP SDK version drift — pin the `mcp` package version in `pyproject.toml` from CP1 and
  note it here so CP6's Recipe MCP server uses the same pinned version.

## Notes

This server must remain "dumb" — no budget/dietary/cart logic here. If a future change adds
scoring or preference logic to this file, that is a signal it belongs in CP4/CP7 instead.

## Definition of Done

- [ ] All three tools implemented and contract-tested.
- [ ] Per-retailer staleness verified independent.
- [ ] `ruff check` clean, tests green, committed referencing CP3.
