# CP2 — Data Model, Database Layer & Ingestion Pipeline

Spec milestone: M1. Depends on: CP1.

## Goal

Implement the per-retailer product/price model behind SQLAlchemy, and the ingestion
pipeline that turns Shufersal Online (`StoreId 413`) and Rami Levy Online (`StoreId 39`)
price-transparency feeds into it via a validated staging load with atomic activation
(spec §5).

## Scope

DB model, `DATABASE_URL`-driven session setup, a repository layer, per-retailer feed
parsers, stage→validate→activate, per-retailer freshness tracking, fixture feed data. No
MCP server yet (CP3 consumes this layer).

**Key design point (spec §3/Data Model)**: there is **one** table, not a
canonical-product/offer split. Each retailer's catalog is independent — a row is keyed by
`(retailer, item_code)`. There is no cross-retailer product identity in the MVP.

## Deliverables

- `python -m app.ingestion.run --source fixtures` loads sample data into local SQLite.
- `ProductRepository.search_candidates(query, retailer)` searches **one retailer's**
  catalog and returns matching rows.
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

1. Write `app/db/models.py`:
   ```python
   from datetime import datetime

   from sqlalchemy import Boolean, DateTime, Float, String
   from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

   ONLINE_STORE_IDS = {"shufersal": "413", "rami_levy": "39"}


   class Base(DeclarativeBase):
       pass


   class RetailerProduct(Base):
       __tablename__ = "retailer_products"

       id: Mapped[int] = mapped_column(primary_key=True)
       retailer: Mapped[str] = mapped_column(String(32), index=True)  # "shufersal" | "rami_levy"
       store_id: Mapped[str] = mapped_column(String(16))  # ONLINE_STORE_IDS[retailer]
       item_code: Mapped[str] = mapped_column(String(64), index=True)
       name: Mapped[str] = mapped_column(String(256))
       category: Mapped[str] = mapped_column(String(128))
       package_size: Mapped[float] = mapped_column(Float)
       package_unit: Mapped[str] = mapped_column(String(16))  # g|kg|ml|l|unit
       price: Mapped[float] = mapped_column(Float)
       listed_in_feed: Mapped[bool] = mapped_column(Boolean, default=True)
       last_updated_at: Mapped[datetime] = mapped_column(DateTime)


   class RetailerFeedStatus(Base):
       __tablename__ = "retailer_feed_status"

       retailer: Mapped[str] = mapped_column(String(32), primary_key=True)
       last_updated_at: Mapped[datetime] = mapped_column(DateTime)
       stale: Mapped[bool] = mapped_column(Boolean, default=False)
   ```
   A unique constraint on `(retailer, item_code)` (add via `__table_args__ =
   (UniqueConstraint("retailer", "item_code"),)`) is what ingestion upserts against.
2. Write `app/db/session.py` with an `init_db()` that creates tables if missing, called once
   at app startup (CP5) so a fresh SQLite file or fresh deployed Postgres (CP11) gets its
   schema with no manual step. (CP12 later replaces this with Alembic migrations.)
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
3. Write `app/db/repositories.py`:
   ```python
   from sqlalchemy import select
   from sqlalchemy.orm import Session

   from app.db.models import RetailerProduct

   UNIT_TO_BASE = {"g": 1, "kg": 1000, "ml": 1, "l": 1000, "unit": 1}


   def unit_price(price: float, package_size: float, package_unit: str) -> float:
       base_qty = package_size * UNIT_TO_BASE[package_unit]
       return price / base_qty if base_qty else price


   class ProductRepository:
       def __init__(self, session: Session):
           self.session = session

       def search_candidates(self, query: str, retailer: str, limit: int = 5) -> list[RetailerProduct]:
           stmt = (
               select(RetailerProduct)
               .where(RetailerProduct.retailer == retailer, RetailerProduct.name.ilike(f"%{query}%"))
               .limit(limit)
           )
           return list(self.session.scalars(stmt))

       def get_product(self, retailer: str, item_code: str) -> RetailerProduct | None:
           stmt = select(RetailerProduct).where(
               RetailerProduct.retailer == retailer, RetailerProduct.item_code == item_code
           )
           return self.session.scalars(stmt).first()
   ```
4. Write the failing test `tests/db/test_repositories.py` for both methods, scoped per
   retailer (searching `"shufersal"` never returns a `"rami_levy"` row and vice versa); seed
   rows via the model class, confirm green.
5. Build two tiny, real-shaped fixture feeds (`shufersal_sample.xml`, `rami_levy_sample.xml`)
   from a real downloaded sample of each chain's Online-store feed (check the schema, don't
   invent it), each with a `<StoreId>` matching `413`/`39`, plus one corrupt variant.
6. Write `app/ingestion/feeds/shufersal.py` and `rami_levy.py`, each exposing
   `parse(xml_bytes) -> list[ParsedProduct]` (`item_code`, `name`, `price`, `package_size`,
   `package_unit`, `store_id`), validating `store_id` matches that module's expected
   `ONLINE_STORE_IDS` entry and raising `FeedValidationError` otherwise. Write
   `tests/ingestion/test_feed_parsers.py` (both retailers parse; corrupt/wrong-`StoreId`
   feeds raise).
7. Write `app/ingestion/pipeline.py`:
   ```python
   from datetime import datetime, timezone

   from sqlalchemy.orm import Session

   from app.db.models import RetailerFeedStatus, RetailerProduct


   class FeedValidationError(Exception):
       pass


   def ingest_retailer_feed(session: Session, retailer: str, parsed_products: list) -> None:
       if not parsed_products:
           raise FeedValidationError(f"{retailer}: feed produced zero products, refusing to activate")

       with session.begin():
           session.query(RetailerProduct).filter_by(retailer=retailer).delete()
           for item in parsed_products:
               session.add(
                   RetailerProduct(
                       retailer=retailer,
                       store_id=item.store_id,
                       item_code=item.item_code,
                       name=item.name,
                       category="uncategorized",
                       package_size=item.package_size,
                       package_unit=item.package_unit,
                       price=item.price,
                       listed_in_feed=True,
                       last_updated_at=datetime.now(timezone.utc),
                   )
               )
           session.merge(
               RetailerFeedStatus(retailer=retailer, last_updated_at=datetime.now(timezone.utc), stale=False)
           )
   ```
   The `session.begin()` block is the atomic-activation boundary — any exception before it
   completes rolls back, leaving the previously-active rows untouched.
8. Write `tests/ingestion/test_pipeline_atomic_swap.py`: a load that fails partway leaves
   existing rows unchanged; a zero-row feed refuses to activate.
9. Write `tests/ingestion/test_freshness.py`: add an `is_stale(status, threshold_hours=48)`
   helper to `pipeline.py`, test with frozen/injected timestamps.
10. Write `app/ingestion/run.py` as a CLI (`--source fixtures`) that loads both fixture
    files through `ingest_retailer_feed` for their respective retailers.
11. Run the CLI against local SQLite, inspect `retailer_products` for expected `store_id`
    values; run the full test suite; `ruff check`; commit.

## Testing Tasks

- [x] `test_repositories.py` — per-retailer search + lookup.
- [x] `test_feed_parsers.py` — both retailers parse; corrupt/wrong-`StoreId` raises.
- [x] `test_pipeline_atomic_swap.py` — failed/zero-row load never corrupts existing data.
- [x] `test_freshness.py` — staleness threshold logic.

## Acceptance Criteria

Ingestion populates two independent per-retailer catalogs from fixtures; a bad feed is
rejected without side effects; the repository only ever returns one retailer's own products.

## Risks

- Real feed schemas may differ from hand-built fixtures — check one real sample per chain
  before finalizing fixtures.

## Notes

CP3's MCP server calls `ProductRepository` directly — no cross-retailer query lives here or
there. Real live ingestion (CronJob) is CP11; this checkpoint only proves the pipeline
against fixtures.

## Definition of Done

- [x] All files created and wired; tests green; `ruff check` clean.
- [x] CLI run against fixtures verified manually.
- [x] Committed with message referencing CP2.
