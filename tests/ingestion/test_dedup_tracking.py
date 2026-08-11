import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, RetailerFeedStatus
from app.ingestion.feeds import ParsedProduct
from app.ingestion.pipeline import (
    FeedType,
    FeedValidationError,
    already_processed,
    ingest_retailer_feed,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session


def _product(item_code="1") -> ParsedProduct:
    return ParsedProduct(
        item_code=item_code, name="a", price=1.0, package_size=1.0, package_unit="unit", store_id="413"
    )


def test_not_processed_before_any_ingestion(session):
    assert already_processed(session, "shufersal", FeedType.PRICE_FULL, "PriceFull-123.gz") is False


def test_full_feed_is_marked_processed_after_success(session):
    ingest_retailer_feed(
        session, "shufersal", [_product()], feed_type=FeedType.PRICE_FULL, source_filename="PriceFull-123.gz"
    )
    assert already_processed(session, "shufersal", FeedType.PRICE_FULL, "PriceFull-123.gz") is True
    assert already_processed(session, "shufersal", FeedType.PRICE_FULL, "PriceFull-456.gz") is False


def test_full_and_delta_dedup_tracked_independently(session):
    ingest_retailer_feed(
        session, "shufersal", [_product()], feed_type=FeedType.PRICE_FULL, source_filename="PriceFull-123.gz"
    )
    # A delta file with a coincidentally-identical name isn't considered processed —
    # PRICE_FULL and PRICE track their own last-seen filename separately.
    assert already_processed(session, "shufersal", FeedType.PRICE, "PriceFull-123.gz") is False
    # already_processed's session.get() autobegins a transaction (SQLAlchemy 2.0) — end it
    # before the next explicit session.begin() inside ingest_retailer_feed, same fix as
    # app/ingestion/run.py's separate-session-scopes approach, just via rollback here since
    # it was a read-only check.
    session.rollback()

    ingest_retailer_feed(
        session, "shufersal", [_product()], feed_type=FeedType.PRICE, source_filename="Price-789.gz"
    )
    assert already_processed(session, "shufersal", FeedType.PRICE, "Price-789.gz") is True
    # Ingesting a delta doesn't overwrite the tracked full-feed filename.
    assert already_processed(session, "shufersal", FeedType.PRICE_FULL, "PriceFull-123.gz") is True


def test_failed_feed_is_not_marked_processed(session):
    with pytest.raises(FeedValidationError):
        ingest_retailer_feed(
            session, "shufersal", [], feed_type=FeedType.PRICE_FULL, source_filename="PriceFull-empty.gz"
        )
    assert session.get(RetailerFeedStatus, "shufersal") is None
    assert already_processed(session, "shufersal", FeedType.PRICE_FULL, "PriceFull-empty.gz") is False


def test_fixture_mode_leaves_no_source_filename(session):
    """load_fixtures() (app/ingestion/run.py) never passes source_filename — confirms that
    path still behaves exactly as before this feature existed."""
    ingest_retailer_feed(session, "shufersal", [_product()], feed_type=FeedType.PRICE_FULL)
    status = session.get(RetailerFeedStatus, "shufersal")
    assert status.last_full_filename is None
