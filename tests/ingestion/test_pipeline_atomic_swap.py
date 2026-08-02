from datetime import datetime, timedelta, timezone

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


def test_price_delta_updates_existing_product(session):
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
            last_updated_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    session.commit()

    changed_price_only = [
        ParsedProduct(
            item_code="1",
            name="original name",
            price=6.0,
            package_size=2.0,
            package_unit="unit",
            store_id="413",
        )
    ]

    before = datetime.now(timezone.utc).replace(tzinfo=None)
    ingest_retailer_feed(session, "shufersal", changed_price_only, feed_type=FeedType.PRICE)

    remaining = session.scalars(select(RetailerProduct)).all()
    assert len(remaining) == 1
    assert remaining[0].item_code == "1"
    assert remaining[0].price == 6.0
    assert remaining[0].package_size == 2.0
    assert remaining[0].last_updated_at >= before


def test_price_delta_inserts_new_product(session):
    session.add(
        RetailerProduct(
            retailer="shufersal",
            store_id="413",
            item_code="1",
            name="existing",
            category="uncategorized",
            package_size=1.0,
            package_unit="unit",
            price=5.0,
            listed_in_feed=True,
            last_updated_at=datetime.now(timezone.utc),
        )
    )
    session.commit()

    new_product = [
        ParsedProduct(
            item_code="2", name="brand new", price=3.5, package_size=1.0, package_unit="unit", store_id="413"
        )
    ]

    ingest_retailer_feed(session, "shufersal", new_product, feed_type=FeedType.PRICE)

    remaining = {p.item_code: p for p in session.scalars(select(RetailerProduct)).all()}
    assert set(remaining) == {"1", "2"}
    assert remaining["2"].name == "brand new"
    assert remaining["2"].price == 3.5


def test_price_delta_leaves_unrelated_products_unchanged(session):
    untouched_last_updated = datetime.now(timezone.utc) - timedelta(days=2)
    session.add(
        RetailerProduct(
            retailer="shufersal",
            store_id="413",
            item_code="1",
            name="unrelated product",
            category="uncategorized",
            package_size=1.0,
            package_unit="unit",
            price=5.0,
            listed_in_feed=True,
            last_updated_at=untouched_last_updated,
        )
    )
    session.add(
        RetailerProduct(
            retailer="shufersal",
            store_id="413",
            item_code="2",
            name="changed product",
            category="uncategorized",
            package_size=1.0,
            package_unit="unit",
            price=5.0,
            listed_in_feed=True,
            last_updated_at=datetime.now(timezone.utc),
        )
    )
    session.commit()

    delta = [
        ParsedProduct(
            item_code="2", name="changed product", price=9.0, package_size=1.0, package_unit="unit", store_id="413"
        )
    ]

    ingest_retailer_feed(session, "shufersal", delta, feed_type=FeedType.PRICE)

    unrelated = session.scalars(
        select(RetailerProduct).where(RetailerProduct.item_code == "1")
    ).one()
    assert unrelated.price == 5.0
    assert unrelated.name == "unrelated product"
    assert unrelated.last_updated_at == untouched_last_updated.replace(tzinfo=None)


def test_price_delta_rolls_back_entirely_on_failure(session):
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

    duplicate_new_item_codes = [
        ParsedProduct(
            item_code="new-1", name="a", price=1.0, package_size=1.0, package_unit="unit", store_id="413"
        ),
        ParsedProduct(
            item_code="new-1", name="b", price=2.0, package_size=1.0, package_unit="unit", store_id="413"
        ),
    ]

    with pytest.raises(IntegrityError):
        ingest_retailer_feed(session, "shufersal", duplicate_new_item_codes, feed_type=FeedType.PRICE)

    session.rollback()

    remaining = session.scalars(select(RetailerProduct)).all()
    assert len(remaining) == 1
    assert remaining[0].item_code == "1"
    assert remaining[0].price == 5.0
