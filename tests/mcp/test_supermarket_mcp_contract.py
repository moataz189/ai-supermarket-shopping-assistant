from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, RetailerFeedStatus, RetailerProduct
from mcp_servers.supermarket_mcp import server


@pytest.fixture
def db_session_factory(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_session_local = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(server, "SessionLocal", test_session_local)
    return test_session_local


def _make_product(
    retailer: str,
    item_code: str,
    name: str,
    store_id: str,
    price: float = 9.9,
    package_size: float = 1.0,
    package_unit: str = "unit",
    listed_in_feed: bool = True,
) -> RetailerProduct:
    return RetailerProduct(
        retailer=retailer,
        store_id=store_id,
        item_code=item_code,
        name=name,
        category="uncategorized",
        package_size=package_size,
        package_unit=package_unit,
        price=price,
        listed_in_feed=listed_in_feed,
        last_updated_at=datetime.now(timezone.utc),
    )


def test_search_product_only_returns_requested_retailer(db_session_factory):
    with db_session_factory() as session:
        session.add(_make_product("shufersal", "1", "חלב תנובה", "413"))
        session.add(_make_product("rami_levy", "2", "חלב תנובה", "39"))
        session.commit()

    result = server.search_product("חלב", "shufersal")

    assert [c.item_code for c in result.candidates] == ["1"]


def test_search_product_does_not_leak_other_retailer(db_session_factory):
    with db_session_factory() as session:
        session.add(_make_product("shufersal", "1", "עגבניה", "413"))
        session.add(_make_product("rami_levy", "2", "עגבניה", "39"))
        session.commit()

    shufersal_result = server.search_product("עגבניה", "shufersal")
    rami_levy_result = server.search_product("עגבניה", "rami_levy")

    assert {c.item_code for c in shufersal_result.candidates} == {"1"}
    assert {c.item_code for c in rami_levy_result.candidates} == {"2"}


def test_get_product_price_returns_expected_fields(db_session_factory):
    with db_session_factory() as session:
        session.add(
            _make_product(
                "shufersal", "100", "חלב", "413", price=6.0, package_size=2.0, package_unit="l"
            )
        )
        session.add(
            RetailerFeedStatus(
                retailer="shufersal", last_updated_at=datetime.now(timezone.utc), stale=False
            )
        )
        session.commit()

    result = server.get_product_price("shufersal", "100")

    assert result is not None
    assert result.retailer == "shufersal"
    assert result.store_id == "413"
    assert result.item_code == "100"
    assert result.price == 6.0
    assert result.unit_price == 0.003
    assert result.listed_in_feed is True
    assert result.stale is False
    assert result.last_updated_at


def test_get_product_price_independent_stale_per_retailer(db_session_factory):
    now = datetime.now(timezone.utc)
    with db_session_factory() as session:
        session.add(_make_product("shufersal", "1", "לחם", "413"))
        session.add(_make_product("rami_levy", "1", "לחם", "39"))
        session.add(RetailerFeedStatus(retailer="shufersal", last_updated_at=now, stale=True))
        session.add(RetailerFeedStatus(retailer="rami_levy", last_updated_at=now, stale=False))
        session.commit()

    shufersal_price = server.get_product_price("shufersal", "1")
    rami_levy_price = server.get_product_price("rami_levy", "1")

    assert shufersal_price.store_id == "413"
    assert rami_levy_price.store_id == "39"
    assert shufersal_price.stale is True
    assert rami_levy_price.stale is False


def test_get_product_price_returns_none_for_missing_product(db_session_factory):
    result = server.get_product_price("shufersal", "does-not-exist")

    assert result is None
