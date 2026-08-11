from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RetailerFeedStatus, RetailerProduct


class FeedType(str, Enum):
    """Israeli price-transparency feed file types, per retailer/store.

    PRICE_FULL: a complete snapshot of every product and its current regular
    price; rebuilds the entire catalog from scratch. Treated as the
    authoritative baseline.

    PRICE: a delta feed containing only products whose regular price changed
    since the previous publication. Updates an existing catalog in place
    (per-item upsert) rather than rebuilding it — see `ingest_retailer_feed`.
    """

    PRICE_FULL = "PriceFull"
    PRICE = "Price"


class FeedValidationError(Exception):
    pass


def already_processed(
    session: Session, retailer: str, feed_type: FeedType, source_filename: str
) -> bool:
    """True if this exact source file was already the last one successfully ingested for
    this retailer/feed_type — lets a caller skip re-downloading/re-parsing/re-ingesting a
    file it's already processed (the hourly Price delta poll runs more often than the
    upstream file necessarily changes)."""
    status = session.get(RetailerFeedStatus, retailer)
    if status is None:
        return False
    last_filename = (
        status.last_full_filename if feed_type is FeedType.PRICE_FULL else status.last_delta_filename
    )
    return last_filename == source_filename


def ingest_retailer_feed(
    session: Session,
    retailer: str,
    parsed_products: list,
    feed_type: FeedType = FeedType.PRICE_FULL,
    source_filename: str | None = None,
) -> None:
    """Ingest one already-parsed feed for one retailer.

    This is the single reusable ingestion entry point for both feed types; the hourly
    live-delta run calls it directly for each newly downloaded `Price` file.
    `source_filename` (the feed's origin filename, e.g.
    "PriceFull7290027600007-002-413-20260811-034000.gz") is recorded on
    `RetailerFeedStatus` only if this call succeeds — never on a failed/rolled-back
    transaction — so `already_processed` can reliably detect a duplicate. `None` for
    fixture-loaded data, which has no real source filename to track.
    """
    if feed_type is FeedType.PRICE_FULL:
        _ingest_price_full(session, retailer, parsed_products, source_filename)
    else:
        _ingest_price_delta(session, retailer, parsed_products, source_filename)


def _ingest_price_full(
    session: Session, retailer: str, parsed_products: list, source_filename: str | None
) -> None:
    """Validate, then atomically replace the retailer's entire active catalog."""
    if not parsed_products:
        raise FeedValidationError(f"{retailer}: feed produced zero products, refusing to activate")

    with session.begin():
        session.query(RetailerProduct).filter_by(retailer=retailer).delete()
        for item in parsed_products:
            session.add(_new_product(retailer, item))
        _touch_freshness(session, retailer, FeedType.PRICE_FULL, source_filename)


def _ingest_price_delta(
    session: Session, retailer: str, parsed_products: list, source_filename: str | None
) -> None:
    """Upsert only the products present in the delta; leave the rest of the catalog alone.

    Runs as one transaction: any failure (a bad item, a DB constraint
    violation) rolls back every change from this delta, leaving the catalog
    exactly as it was before this file.
    """
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
        _touch_freshness(session, retailer, FeedType.PRICE, source_filename)


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


def _touch_freshness(
    session: Session, retailer: str, feed_type: FeedType, source_filename: str | None
) -> None:
    existing = session.get(RetailerFeedStatus, retailer)
    last_full_filename = existing.last_full_filename if existing else None
    last_delta_filename = existing.last_delta_filename if existing else None
    if feed_type is FeedType.PRICE_FULL:
        last_full_filename = source_filename
    else:
        last_delta_filename = source_filename

    session.merge(
        RetailerFeedStatus(
            retailer=retailer,
            last_updated_at=datetime.now(timezone.utc),
            stale=False,
            last_full_filename=last_full_filename,
            last_delta_filename=last_delta_filename,
        )
    )


def is_stale(status: RetailerFeedStatus, threshold_hours: int = 48) -> bool:
    return datetime.now(timezone.utc) - status.last_updated_at > timedelta(hours=threshold_hours)
