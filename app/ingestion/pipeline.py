from datetime import datetime, timedelta, timezone

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


def is_stale(status: RetailerFeedStatus, threshold_hours: int = 48) -> bool:
    return datetime.now(timezone.utc) - status.last_updated_at > timedelta(hours=threshold_hours)
