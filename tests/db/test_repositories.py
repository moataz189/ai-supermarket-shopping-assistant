from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, RetailerProduct
from app.db.repositories import (
    IngredientTranslationRepository,
    ProductRepository,
    canonicalize_ingredient_name,
    seed_ingredient_translations,
)


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


def test_canonicalize_ingredient_name_normalizes_case_and_whitespace():
    assert canonicalize_ingredient_name("  Heavy Cream  ") == "heavy cream"


def test_ingredient_translation_save_then_get(session):
    repo = IngredientTranslationRepository(session)

    repo.save_many([("pasta", "pasta", "פסטה")])
    found = repo.get_many(["pasta", "unknown"])

    assert set(found) == {"pasta"}
    assert found["pasta"].original_name == "pasta"
    assert found["pasta"].search_name_he == "פסטה"


def test_ingredient_translation_get_many_empty_input_returns_empty_dict(session):
    repo = IngredientTranslationRepository(session)
    assert repo.get_many([]) == {}


def test_seed_ingredient_translations_populates_known_terms(session):
    seed_ingredient_translations(session)

    repo = IngredientTranslationRepository(session)
    found = repo.get_many(["tomatoes", "onion", "milk"])

    assert found["tomatoes"].search_name_he == "עגבניה"  # singular, not "עגבניות"
    assert found["onion"].search_name_he == "בצל"
    assert found["milk"].search_name_he == "חלב"


def test_seed_ingredient_translations_is_idempotent_and_never_overwrites(session):
    seed_ingredient_translations(session)
    repo = IngredientTranslationRepository(session)
    # Simulate a manually-corrected entry — re-seeding must never clobber it.
    tomatoes_row = repo.get_many(["tomatoes"])["tomatoes"]
    tomatoes_row.search_name_he = "עגבניה מיוחדת"
    session.commit()

    seed_ingredient_translations(session)

    assert repo.get_many(["tomatoes"])["tomatoes"].search_name_he == "עגבניה מיוחדת"
