# CP2 — Data Model, Database Layer & Ingestion Pipeline

Spec milestone: M1. Depends on: CP1.

## Goal

Implement the canonical-product / retailer-offer data model behind SQLAlchemy, and the
ingestion pipeline that turns Shufersal Online (`StoreId 413`) and Rami Levy Online
(`StoreId 39`) price-transparency feeds into that model via a validated staging load with
atomic dataset activation (spec §5).

## Scope

DB models, `DATABASE_URL`-driven session setup, a repository layer, per-retailer feed
parsers, the stage→validate→activate pipeline, per-retailer freshness/staleness tracking,
and fixture feed data for local dev/tests. No MCP server yet (CP3 consumes this layer).

## Deliverables

- `python -m app.ingestion.run --source fixtures` loads sample data into local SQLite.
- `ProductRepository` can search candidates by name and return each retailer's offer for a
  product, keyed by `retailer`, sourced from that retailer's fixed Online `StoreId`.
- A corrupted/partial feed load never mutates previously-activated data.

## Files to Create

```
app/db/__init__.py
app/db/models.py
app/db/session.py
app/db/repositories.py
app/ingestion/__init__.py
app/ingestion/feeds/__init__.py
app/ingestion/feeds/shufersal.py
app/ingestion/feeds/rami_levy.py
app/ingestion/pipeline.py
app/ingestion/run.py
tests/fixtures/feeds/shufersal_sample.xml
tests/fixtures/feeds/rami_levy_sample.xml
tests/fixtures/feeds/shufersal_corrupt.xml
tests/db/test_repositories.py
tests/ingestion/test_feed_parsers.py
tests/ingestion/test_pipeline_atomic_swap.py
tests/ingestion/test_freshness.py
```

## Detailed Implementation Steps

1. Write `app/db/models.py`. Each retailer offer is keyed by that retailer's own `ItemCode`
   at a **fixed** `StoreId` — Shufersal Online is always `413`, Rami Levy Online is always
   `39` — since the MVP only ever ingests, prices, and later automates against each
   retailer's Online store (spec §2/§3):
   ```python
   from datetime import datetime

   from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String
   from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

   ONLINE_STORE_IDS = {"shufersal": "413", "rami_levy": "39"}


   class Base(DeclarativeBase):
       pass


   class CanonicalProduct(Base):
       __tablename__ = "canonical_products"

       id: Mapped[int] = mapped_column(primary_key=True)
       product_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
       barcode: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
       name: Mapped[str] = mapped_column(String(256))
       category: Mapped[str] = mapped_column(String(128))
       package_size: Mapped[float] = mapped_column(Float)
       package_unit: Mapped[str] = mapped_column(String(16))  # g|kg|ml|l|unit

       offers: Mapped[list["RetailerOffer"]] = relationship(back_populates="product")


   class RetailerOffer(Base):
       __tablename__ = "retailer_offers"

       id: Mapped[int] = mapped_column(primary_key=True)
       product_id: Mapped[str] = mapped_column(
           ForeignKey("canonical_products.product_id"), index=True
       )
       retailer: Mapped[str] = mapped_column(String(32), index=True)  # "shufersal" | "rami_levy"
       store_id: Mapped[str] = mapped_column(String(16))  # ONLINE_STORE_IDS[retailer]
       item_code: Mapped[str] = mapped_column(String(64))  # the retailer's ItemCode from the feed
       price: Mapped[float] = mapped_column(Float)
       listed_in_feed: Mapped[bool] = mapped_column(Boolean, default=True)
       last_updated_at: Mapped[datetime] = mapped_column(DateTime)

       product: Mapped["CanonicalProduct"] = relationship(back_populates="offers")


   class RetailerFeedStatus(Base):
       __tablename__ = "retailer_feed_status"

       retailer: Mapped[str] = mapped_column(String(32), primary_key=True)
       last_updated_at: Mapped[datetime] = mapped_column(DateTime)
       stale: Mapped[bool] = mapped_column(Boolean, default=False)
   ```
2. Write `app/db/session.py`, including an `init_db()` helper that creates all tables if
   they don't already exist — called once at application startup (wired into
   `app/api/main.py` in CP5) so both a fresh local SQLite file and a fresh deployed Postgres
   database (CP11) get their schema without any manual step. (CP12 later introduces Alembic
   migrations as the permanent schema-management mechanism; see that checkpoint's note on
   reconciling this with an already `init_db()`-created database.)
   ```python
   import os

   from sqlalchemy import create_engine
   from sqlalchemy.orm import sessionmaker

   from app.db.models import Base

   DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./app.db")

   engine = create_engine(DATABASE_URL, future=True)
   SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


   def init_db() -> None:
       Base.metadata.create_all(bind=engine)
   ```
   Modify `app/api/main.py` (CP1) to call `init_db()` once at import time (module-level
   call, right after the FastAPI `app` is created) so both `uvicorn` runs and the ingestion
   CLI (which also imports `app.db.session`) get the schema created on first use.
3. Write the unit price helper and `ProductRepository` in `app/db/repositories.py`. Because
   each retailer is only ever ingested from its one fixed Online `StoreId`, there is at most
   one offer row per `(product_id, retailer)` — no branch aggregation/minimum-picking is
   needed (a deliberate simplification unlocked by always using the Online store, per
   spec §3):
   ```python
   from sqlalchemy import select
   from sqlalchemy.orm import Session

   from app.db.models import CanonicalProduct, RetailerOffer

   UNIT_TO_BASE = {"g": 1, "kg": 1000, "ml": 1, "l": 1000, "unit": 1}


   def unit_price(price: float, package_size: float, package_unit: str) -> float:
       base_qty = package_size * UNIT_TO_BASE[package_unit]
       return price / base_qty if base_qty else price


   class ProductRepository:
       def __init__(self, session: Session):
           self.session = session

       def search_candidates(self, query: str, limit: int = 5) -> list[CanonicalProduct]:
           stmt = (
               select(CanonicalProduct)
               .where(CanonicalProduct.name.ilike(f"%{query}%"))
               .limit(limit)
           )
           return list(self.session.scalars(stmt))

       def get_offers_by_retailer(self, product_id: str) -> dict[str, RetailerOffer]:
           """This product's offer at each retailer's Online store, keyed by retailer."""
           stmt = select(RetailerOffer).where(RetailerOffer.product_id == product_id)
           return {offer.retailer: offer for offer in self.session.scalars(stmt)}
   ```
4. Write the failing test `tests/db/test_repositories.py` covering `search_candidates` and
   `get_offers_by_retailer` against an in-memory SQLite session fixture; run it, watch it
   fail (no data yet), then seed rows directly via the model classes in the test and confirm
   it passes.
5. Build two tiny, real-shaped fixture feeds by hand in
   `tests/fixtures/feeds/shufersal_sample.xml` and `rami_levy_sample.xml` (a handful of
   items each, matching the real chains' published Online-store price-transparency XML
   structure — check one real downloaded sample file from each chain's transparency portal
   first, so the fixture schema is accurate, including a `<StoreId>` element matching
   `413`/`39` respectively) and one corrupt/truncated variant, `shufersal_corrupt.xml`.
6. Write `app/ingestion/feeds/shufersal.py` and `rami_levy.py`, each exposing
   `parse(xml_bytes: bytes) -> list[ParsedOffer]` where `ParsedOffer` is a small dataclass
   (`barcode`, `item_code`, `name`, `price`, `package_size`, `package_unit`, `store_id`).
   `parse()` must validate that every row's `store_id` matches the expected
   `ONLINE_STORE_IDS` value for that module's retailer (`"413"` for `shufersal.py`, `"39"`
   for `rami_levy.py`) and raise `FeedValidationError` if a row's `StoreId` doesn't match —
   this guards against accidentally ingesting a different branch's feed file. Write
   `tests/ingestion/test_feed_parsers.py` against the two sample fixtures first (red, then
   implement until green); add cases asserting `parse()` raises a `FeedValidationError` on
   `shufersal_corrupt.xml` and on a fixture row with an unexpected `StoreId`.
7. Write `app/ingestion/pipeline.py` implementing stage→validate→activate:
   ```python
   from datetime import datetime, timezone

   from sqlalchemy.orm import Session

   from app.db.models import CanonicalProduct, RetailerFeedStatus, RetailerOffer


   class FeedValidationError(Exception):
       pass


   def ingest_retailer_feed(session: Session, retailer: str, parsed_offers: list) -> None:
       if not parsed_offers:
           raise FeedValidationError(f"{retailer}: feed produced zero offers, refusing to activate")

       with session.begin():
           for item in parsed_offers:
               product = session.get(CanonicalProduct, item.barcode) or CanonicalProduct(
                   product_id=item.barcode or item.item_code,
                   barcode=item.barcode,
                   name=item.name,
                   category="uncategorized",
                   package_size=item.package_size,
                   package_unit=item.package_unit,
               )
               session.merge(product)

           session.query(RetailerOffer).filter_by(retailer=retailer).delete()
           for item in parsed_offers:
               session.add(
                   RetailerOffer(
                       product_id=item.barcode or item.item_code,
                       retailer=retailer,
                       store_id=item.store_id,
                       item_code=item.item_code,
                       price=item.price,
                       listed_in_feed=True,
                       last_updated_at=datetime.now(timezone.utc),
                   )
               )
           session.merge(
               RetailerFeedStatus(
                   retailer=retailer,
                   last_updated_at=datetime.now(timezone.utc),
                   stale=False,
               )
           )
   ```
   The `session.begin()` block is the atomic-activation boundary: any exception before it
   completes rolls back the whole transaction, leaving the previously-active
   `RetailerOffer` rows for that retailer untouched.
8. Write `tests/ingestion/test_pipeline_atomic_swap.py`: seed one retailer's offers, then
   call `ingest_retailer_feed` with a parsed list that raises partway through (simulate by
   passing a list containing an object that fails validation), and assert the original rows
   are still present and unchanged afterward. Also test the zero-offers guard raises
   `FeedValidationError` without touching existing rows.
9. Write `tests/ingestion/test_freshness.py`: assert `RetailerFeedStatus.stale` is computed
   `True` when `last_updated_at` is older than a configurable threshold (e.g. 48h) — add a
   small `is_stale(status, threshold_hours=48)` helper function to `pipeline.py` and test it
   directly with frozen/injected timestamps (no real sleep).
10. Write `app/ingestion/run.py` as a CLI entrypoint:
    ```python
    import argparse

    from app.db.session import SessionLocal
    from app.ingestion.feeds import rami_levy, shufersal
    from app.ingestion.pipeline import ingest_retailer_feed

    FEEDS = {
        "shufersal": ("tests/fixtures/feeds/shufersal_sample.xml", shufersal),
        "rami_levy": ("tests/fixtures/feeds/rami_levy_sample.xml", rami_levy),
    }


    def main() -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--source", choices=["fixtures"], default="fixtures")
        parser.parse_args()

        with SessionLocal() as session:
            for retailer, (path, module) in FEEDS.items():
                with open(path, "rb") as f:
                    parsed = module.parse(f.read())
                ingest_retailer_feed(session, retailer, parsed)


    if __name__ == "__main__":
        main()
    ```
11. Run `python -m app.ingestion.run --source fixtures` against local SQLite; inspect the DB
    (`sqlite3 app.db "select * from retailer_offers;"`) to confirm rows landed with the
    expected `store_id` values (`413`/`39`).
12. Run the full test suite (`pytest tests/db tests/ingestion -v`), fix failures, then
    `ruff check`, then commit.

## Testing Tasks

- [ ] `test_repositories.py` — candidate search + per-retailer offer lookup.
- [ ] `test_feed_parsers.py` — both retailers parse correctly; corrupt feed raises; a
      mismatched `StoreId` row raises.
- [ ] `test_pipeline_atomic_swap.py` — failed load leaves existing data untouched; zero-row
      feed refuses to activate.
- [ ] `test_freshness.py` — staleness threshold logic.

## Acceptance Criteria

Running the ingestion CLI against fixture feeds populates SQLite with the expected canonical
products and per-retailer Online-store offers; a corrupted feed, or one with an unexpected
`StoreId`, is rejected without side effects; the repository returns each retailer's offer for
a given product.

## Risks

- The real Shufersal/Rami Levy feed schemas may differ subtly from the hand-built fixtures —
  mitigated by checking one real downloaded sample from each chain's transparency portal
  before finalizing the fixtures in step 5, not inventing the schema from memory.

## Notes

CP3's Supermarket-Data MCP server calls `ProductRepository` directly — do not duplicate
query logic there. Real live-feed ingestion (network download, CronJob) is CP11; this
checkpoint only proves the parse→stage→activate logic against fixtures.

## Definition of Done

- [ ] All files above exist and are wired together.
- [ ] All listed tests pass; `ruff check` is clean.
- [ ] CLI run against fixtures verified manually.
- [ ] Committed with message referencing CP2.
