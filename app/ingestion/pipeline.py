from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy.orm import Session

from app.db.models import RetailerFeedStatus, RetailerProduct


class FeedType(str, Enum):
    """Israeli price-transparency feed file types, per retailer/store.

    PRICE_FULL: a complete snapshot of every product and its current regular
    price; can rebuild the entire catalog from scratch. Treated as the
    authoritative baseline — this is the only feed type the MVP ingests.

    PRICE: a delta feed containing only products whose regular price changed
    since the previous publication; intended to update an existing catalog
    rather than rebuild it. `ParsedProduct`'s shape is already delta-shaped
    (a bare list of changed items), so a future implementation only needs to
    replace the branch below with an upsert instead of a full replace —
    `ingest_retailer_feed` deliberately guards on `feed_type` today so that
    seam is explicit rather than silently doing the wrong thing.
    """

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
    if feed_type is not FeedType.PRICE_FULL:
        raise NotImplementedError(
            f"{retailer}: incremental {FeedType.PRICE.value} feed ingestion is not "
            f"implemented yet; only {FeedType.PRICE_FULL.value} (full-catalog snapshot) "
            "ingestion is supported."
        )

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


def is_stale(status: RetailerFeedStatus, threshold_hours: int = 48) -> bool:
    return datetime.now(timezone.utc) - status.last_updated_at > timedelta(hours=threshold_hours)
