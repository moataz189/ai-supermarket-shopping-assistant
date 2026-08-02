from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Base, RetailerFeedStatus, RetailerProduct
from app.ingestion.feeds import ParsedProduct
from app.ingestion.pipeline import FeedType, FeedValidationError, ingest_retailer_feed


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session


def test_zero_row_feed_refuses_to_activate(session):
    with pytest.raises(FeedValidationError):
        ingest_retailer_feed(session, "shufersal", [])

    assert session.scalars(select(RetailerProduct)).first() is None
    assert session.get(RetailerFeedStatus, "shufersal") is None


def test_failed_load_leaves_existing_data_untouched(session):
    session.add(
        RetailerProduct(
            retailer="shufersal",
            store_id="413",
            item_code="1",
            name="original name",
            category="uncategorized",
            package_size=1.0,
            package_unit="unit",
            price=5.0,
            listed_in_feed=True,
            last_updated_at=datetime.now(timezone.utc),
        )
    )
    session.commit()

    duplicate_item_codes = [
        ParsedProduct(
            item_code="2",
            name="a",
            price=1.0,
            package_size=1.0,
            package_unit="unit",
            store_id="413",
        ),
        ParsedProduct(
            item_code="2",
            name="b",
            price=2.0,
            package_size=1.0,
            package_unit="unit",
            store_id="413",
        ),
    ]

    with pytest.raises(IntegrityError):
        ingest_retailer_feed(session, "shufersal", duplicate_item_codes)

    session.rollback()

    remaining = session.scalars(select(RetailerProduct)).all()
    assert len(remaining) == 1
    assert remaining[0].item_code == "1"
    assert remaining[0].name == "original name"


def test_ingest_defaults_to_price_full_and_rebuilds_the_catalog(session):
    products = [
        ParsedProduct(
            item_code="1", name="milk", price=6.0, package_size=1.0, package_unit="l", store_id="413"
        )
    ]

    ingest_retailer_feed(session, "shufersal", products)

    remaining = session.scalars(select(RetailerProduct)).all()
    assert [p.item_code for p in remaining] == ["1"]


def test_ingest_price_full_explicit_feed_type_matches_default(session):
    products = [
        ParsedProduct(
            item_code="1", name="milk", price=6.0, package_size=1.0, package_unit="l", store_id="413"
        )
    ]

    ingest_retailer_feed(session, "shufersal", products, feed_type=FeedType.PRICE_FULL)

    remaining = session.scalars(select(RetailerProduct)).all()
    assert [p.item_code for p in remaining] == ["1"]


def test_incremental_price_feed_type_is_not_yet_implemented(session):
    session.add(
        RetailerProduct(
            retailer="shufersal",
            store_id="413",
            item_code="1",
            name="original name",
            category="uncategorized",
            package_size=1.0,
            package_unit="unit",
            price=5.0,
            listed_in_feed=True,
            last_updated_at=datetime.now(timezone.utc),
        )
    )
    session.commit()

    changed_price_only = [
        ParsedProduct(
            item_code="1",
            name="original name",
            price=6.0,
            package_size=1.0,
            package_unit="unit",
            store_id="413",
        )
    ]

    with pytest.raises(NotImplementedError):
        ingest_retailer_feed(session, "shufersal", changed_price_only, feed_type=FeedType.PRICE)

    remaining = session.scalars(select(RetailerProduct)).all()
    assert len(remaining) == 1
    assert remaining[0].price == 5.0
