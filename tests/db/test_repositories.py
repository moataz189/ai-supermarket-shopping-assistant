from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, RetailerProduct
from app.db.repositories import ProductRepository, _hebrew_plural_singular_variant


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


def test_search_candidates_matches_words_regardless_of_order(session):
    # Real user report: the translated multi-word query "קונכיות פסטה" ("shells pasta")
    # never matched a real product named "...פסטה...קונכיות" ("...pasta...shells") --
    # both words must be present, not the whole phrase as one contiguous substring in
    # that exact order.
    session.add(_make_product("shufersal", "1", "ליגורי פסטה ניוקי סרדי קונכיות 500גר", "413"))
    session.commit()

    repo = ProductRepository(session)
    results = repo.search_candidates("קונכיות פסטה", retailer="shufersal")

    assert [p.item_code for p in results] == ["1"]


def test_search_candidates_requires_all_words_present(session):
    session.add(_make_product("shufersal", "1", "פסטה מקרוני", "413"))  # missing קונכיות
    session.add(_make_product("shufersal", "2", "קונכיות בצק למילוי", "413"))  # missing פסטה
    session.add(_make_product("shufersal", "3", "פסטה קונכיות", "413"))  # has both
    session.commit()

    repo = ProductRepository(session)
    results = repo.search_candidates("קונכיות פסטה", retailer="shufersal")

    assert [p.item_code for p in results] == ["3"]


def test_search_candidates_default_limit_is_broad_enough_for_relevance_filtering_downstream(session):
    # Real user report: the previous default (5, with no ORDER BY) returned an arbitrary
    # slice of whatever matched a common word -- Shufersal's first 5 "garlic" matches out
    # of 116 total were all garlic-*seasoned* products or unrelated substring hits, so the
    # relevance filter downstream never got a real chance to see the genuine match. This
    # doesn't assert an exact number (an implementation detail) -- just that it's
    # meaningfully broader than the old hardcoded 5.
    for i in range(40):
        session.add(_make_product("shufersal", str(i), "שום", "413"))
    session.commit()

    repo = ProductRepository(session)
    results = repo.search_candidates("שום", retailer="shufersal")

    assert len(results) > 5


def test_search_candidates_matches_hebrew_singular_when_query_is_plural(session):
    # Real user report: the translated "pasta shells" query used the plural "קונכיות",
    # but the real Shufersal product used the singular "קונכיה" -- neither is a
    # substring of the other, so a plain per-word ILIKE alone can't bridge them.
    session.add(_make_product("shufersal", "1", "פסטה ניוקטי סרדי קונכיה", "413"))
    session.commit()

    repo = ProductRepository(session)
    results = repo.search_candidates("קונכיות פסטה", retailer="shufersal")

    assert [p.item_code for p in results] == ["1"]


def test_search_candidates_matches_hebrew_plural_when_query_is_singular(session):
    # The reverse direction of the same swap -- a singular query must also find a real
    # plural-named product (e.g. Rami Levy's own "קונכיות" listing for the same shape).
    session.add(_make_product("rami_levy", "1", "ליגורי פסטה ניוקי סרדי קונכיות 500גר", "39"))
    session.commit()

    repo = ProductRepository(session)
    results = repo.search_candidates("קונכיה פסטה", retailer="rami_levy")

    assert [p.item_code for p in results] == ["1"]


def test_search_candidates_still_requires_the_word_or_its_variant_present(session):
    # The plural/singular swap must not become a loose match-anything fallback -- a
    # product missing the word (and its variant) entirely still doesn't match.
    session.add(_make_product("shufersal", "1", "פסטה מקרוני", "413"))  # no קונכיה/קונכיות at all
    session.commit()

    repo = ProductRepository(session)
    results = repo.search_candidates("קונכיות פסטה", retailer="shufersal")

    assert results == []


def test_hebrew_plural_singular_variant_swaps_the_common_feminine_suffix():
    assert _hebrew_plural_singular_variant("קונכיות") == "קונכיה"
    assert _hebrew_plural_singular_variant("קונכיה") == "קונכיות"


def test_hebrew_plural_singular_variant_returns_none_for_words_too_short_or_unmatched():
    assert _hebrew_plural_singular_variant("שום") is None  # no matching suffix at all
    assert _hebrew_plural_singular_variant("ה") is None  # too short for the swap to be meaningful
    assert _hebrew_plural_singular_variant("ות") is None  # too short for the swap to be meaningful


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
