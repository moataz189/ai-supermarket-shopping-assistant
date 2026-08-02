from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, RetailerProduct
from app.db.repositories import ProductRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session


def _make_product(retailer: str, item_code: str, name: str, store_id: str) -> RetailerProduct:
    return RetailerProduct(
        retailer=retailer,
        store_id=store_id,
        item_code=item_code,
        name=name,
        category="uncategorized",
        package_size=1.0,
        package_unit="unit",
        price=9.9,
        listed_in_feed=True,
        last_updated_at=datetime.now(timezone.utc),
    )


def test_search_candidates_only_returns_matching_retailer(session):
    session.add(_make_product("shufersal", "1", "חלב תנובה", "413"))
    session.add(_make_product("rami_levy", "2", "חלב תנובה", "39"))
    session.commit()

    repo = ProductRepository(session)

    shufersal_results = repo.search_candidates("חלב", retailer="shufersal")
    rami_levy_results = repo.search_candidates("חלב", retailer="rami_levy")

    assert [p.retailer for p in shufersal_results] == ["shufersal"]
    assert [p.retailer for p in rami_levy_results] == ["rami_levy"]


def test_search_candidates_respects_limit(session):
    for i in range(10):
        session.add(_make_product("shufersal", str(i), "עגבניה", "413"))
    session.commit()

    repo = ProductRepository(session)
    results = repo.search_candidates("עגבניה", retailer="shufersal", limit=3)

    assert len(results) == 3


def test_get_product_returns_none_when_missing(session):
    repo = ProductRepository(session)
    assert repo.get_product("shufersal", "does-not-exist") is None


def test_get_product_scoped_to_retailer(session):
    session.add(_make_product("shufersal", "100", "מלפפון", "413"))
    session.add(_make_product("rami_levy", "100", "מלפפון אחר", "39"))
    session.commit()

    repo = ProductRepository(session)

    shufersal_product = repo.get_product("shufersal", "100")
    rami_levy_product = repo.get_product("rami_levy", "100")

    assert shufersal_product.name == "מלפפון"
    assert rami_levy_product.name == "מלפפון אחר"
