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

## Feed Types: PriceFull vs. Price

Israeli price-transparency feeds are published as two distinct file types per retailer/store
(see spec §3, Data source):

- **`PriceFull`** — a complete snapshot of every product and its current regular price. It
  can rebuild the entire retailer catalog from scratch and is treated as the **authoritative
  baseline**.
- **`Price`** — a delta/incremental feed containing only products whose regular price
  changed since the previous publication. It's meant to *update* an existing catalog, not
  rebuild it.

Both feed types are implemented via a single reusable entry point,
`app.ingestion.pipeline.ingest_retailer_feed(session, retailer, parsed_products, feed_type)`:

- `feed_type=FeedType.PRICE_FULL` (the default): validates the feed is non-empty, then
  atomically replaces the retailer's entire active catalog (delete-then-reinsert in one
  transaction). This is what `app/ingestion/run.py --source fixtures` calls today.
- `feed_type=FeedType.PRICE`: upserts only the products present in the delta — updates the
  existing `(retailer, item_code)` row if one exists (price, name, package size/unit, store
  ID, `last_updated_at`), otherwise inserts a new row. Every other product already in the
  catalog is left completely untouched. The whole delta is processed in one transaction; any
  failure (a DB constraint violation, a bad item) rolls back the entire delta, leaving the
  catalog exactly as it was before that file.

Because each retailer's per-item feed schema (`ParsedProduct`) is identical between
`PriceFull` and `Price` files — only *which* items are present differs — the parser modules
(`feeds/shufersal.py`, `feeds/rami_levy.py`) needed no changes to support `Price` feeds; only
`ingest_retailer_feed` needed a second code path.

**What's still out of scope (deferred to CP11, spec §5)**: there is no scheduler, no feed-file
discovery/ordering, and no CLI/service mode that runs ingestion hourly yet. CP11's Kubernetes
CronJob is expected to download new `Price` files on its own hourly schedule and call
`ingest_retailer_feed(session, retailer, parsed_products, feed_type=FeedType.PRICE)` once per
downloaded file — the reusable function implemented here is exactly what that CronJob calls;
this checkpoint only proves the function itself against fixtures, not the schedule around it.

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
7. Write `app/ingestion/pipeline.py` (updated post-CP2 with the `FeedType` dispatch described
   above — see "Feed Types: PriceFull vs. Price"):
   ```python
   from datetime import datetime, timezone
   from enum import Enum

   from sqlalchemy import select
   from sqlalchemy.orm import Session

   from app.db.models import RetailerFeedStatus, RetailerProduct


   class FeedType(str, Enum):
       PRICE_FULL = "PriceFull"
       PRICE = "Price"


   class FeedValidationError(Exception):
       pass


   def ingest_retailer_feed(
       session: Session,
       retailer: str,
       parsed_products: list,
       feed_type: FeedType = FeedType.PRICE_FULL,
   ) -> None:
       if feed_type is FeedType.PRICE_FULL:
           _ingest_price_full(session, retailer, parsed_products)
       else:
           _ingest_price_delta(session, retailer, parsed_products)


   def _ingest_price_full(session: Session, retailer: str, parsed_products: list) -> None:
       if not parsed_products:
           raise FeedValidationError(f"{retailer}: feed produced zero products, refusing to activate")

       with session.begin():
           session.query(RetailerProduct).filter_by(retailer=retailer).delete()
           for item in parsed_products:
               session.add(_new_product(retailer, item))
           _touch_freshness(session, retailer)


   def _ingest_price_delta(session: Session, retailer: str, parsed_products: list) -> None:
       with session.begin():
           item_codes = [item.item_code for item in parsed_products]
           existing_by_code = {
               product.item_code: product
               for product in session.scalars(
                   select(RetailerProduct).where(
                       RetailerProduct.retailer == retailer,
                       RetailerProduct.item_code.in_(item_codes),
                   )
               )
           }
           for item in parsed_products:
               existing = existing_by_code.get(item.item_code)
               if existing is None:
                   session.add(_new_product(retailer, item))
               else:
                   existing.name = item.name
                   existing.price = item.price
                   existing.package_size = item.package_size
                   existing.package_unit = item.package_unit
                   existing.store_id = item.store_id
                   existing.listed_in_feed = True
                   existing.last_updated_at = datetime.now(timezone.utc)
           _touch_freshness(session, retailer)


   def _new_product(retailer: str, item) -> RetailerProduct:
       return RetailerProduct(
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


   def _touch_freshness(session: Session, retailer: str) -> None:
       session.merge(
           RetailerFeedStatus(retailer=retailer, last_updated_at=datetime.now(timezone.utc), stale=False)
       )
   ```
   Each `with session.begin():` block is the atomic-activation boundary for that one feed
   file — any exception before it completes rolls back everything from that file (`PriceFull`
   replace or `Price` upserts alike), leaving the previously-active rows untouched.
8. Write `tests/ingestion/test_pipeline_atomic_swap.py`: a `PriceFull` load that fails partway
   leaves existing rows unchanged; a zero-row `PriceFull` feed refuses to activate; a `Price`
   delta updates an existing product, inserts a newly-introduced product, leaves products
   absent from the delta unchanged, and rolls back entirely if any item in it fails.
9. Write `tests/ingestion/test_freshness.py`: add an `is_stale(status, threshold_hours=48)`
   helper to `pipeline.py`, test with frozen/injected timestamps.
10. Write `app/ingestion/run.py` as a CLI (`--source fixtures`) that loads both fixture
    files through `ingest_retailer_feed` for their respective retailers.
11. Run the CLI against local SQLite, inspect `retailer_products` for expected `store_id`
    values; run the full test suite; `ruff check`; commit.

## Testing Tasks

- [x] `test_repositories.py` — per-retailer search + lookup.
- [x] `test_feed_parsers.py` — both retailers parse; corrupt/wrong-`StoreId` raises.
- [x] `test_pipeline_atomic_swap.py` — failed/zero-row `PriceFull` load never corrupts
      existing data.
- [x] `test_freshness.py` — staleness threshold logic.
- [x] `test_pipeline_atomic_swap.py` (added post-CP2) — `FeedType.PRICE` delta ingestion:
      updates an existing product, inserts a newly-introduced product, leaves products absent
      from the delta unchanged, and rolls back entirely (no partial writes) when any item in
      the delta fails.

## Acceptance Criteria

Ingestion populates two independent per-retailer catalogs from fixtures; a bad `PriceFull`
feed is rejected without side effects; a bad `Price` delta rolls back without side effects;
the repository only ever returns one retailer's own products. `ingest_retailer_feed` is the
one reusable entry point for both feed types — CP11 wires a schedule around it but does not
need to change it.

## Risks

- Real feed schemas may differ from hand-built fixtures — check one real sample per chain
  before finalizing fixtures.

## Notes

CP3's MCP server calls `ProductRepository` directly — no cross-retailer query lives here or
there. Real live ingestion (CronJob) is CP11; this checkpoint proves `ingest_retailer_feed`
itself (both `PriceFull` and `Price`) against fixtures — not the schedule around it.

Both feed types are fully implemented — see "Feed Types: PriceFull vs. Price" above. What's
still deliberately **not** built here: any feed-file discovery/ordering, an
already-processed/idempotency ledger, or an hourly CLI/service mode. CP11's CronJob owns
downloading `Price` files and deciding when/how often to call `ingest_retailer_feed`; this
checkpoint only needs the function to be correct and safe to call repeatedly with whatever
delta CP11 hands it.

**Bonus, post-MVP only**: promotion feeds (`PromoFull`/`Promo`) are a separate concern from
pricing and are entirely out of scope here and for the whole MVP. See "Future Enhancements"
in `docs/plan.md` — a dedicated implementation plan for promotion support should only be
written after all 16 checkpoints are complete.

## Definition of Done

- [x] All files created and wired; tests green; `ruff check` clean.
- [x] CLI run against fixtures verified manually.
- [x] Committed with message referencing CP2.
- [x] `PriceFull` and `Price` both implemented behind `ingest_retailer_feed`; contract-tested
      (update/insert/unchanged/rollback for `Price`; atomic replace/refuse-empty for
      `PriceFull`).
