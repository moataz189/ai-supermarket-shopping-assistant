from pathlib import Path

import pytest

from app.ingestion.feeds import rami_levy, shufersal
from app.ingestion.pipeline import FeedValidationError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "feeds"


def test_shufersal_parses_real_sample_feed():
    xml_bytes = (FIXTURES / "shufersal_sample.xml").read_bytes()

    products = shufersal.parse(xml_bytes)

    assert len(products) == 10
    assert all(p.store_id == "413" for p in products)
    by_code = {p.item_code: p for p in products}
    grams_item = by_code["10181040009"]
    assert grams_item.name == "חמאת קקאו יחידה"
    assert grams_item.price == 46.50
    assert grams_item.package_size == 100.0
    assert grams_item.package_unit == "g"


def test_shufersal_maps_known_units():
    xml_bytes = (FIXTURES / "shufersal_sample.xml").read_bytes()

    products = shufersal.parse(xml_bytes)

    assert {p.package_unit for p in products} == {"g", "kg", "ml", "l", "unit"}


def test_shufersal_wrong_store_id_raises():
    xml_bytes = (FIXTURES / "shufersal_corrupt.xml").read_bytes()

    with pytest.raises(FeedValidationError):
        shufersal.parse(xml_bytes)


def test_rami_levy_parses_real_sample_feed():
    xml_bytes = (FIXTURES / "rami_levy_sample.xml").read_bytes()

    products = rami_levy.parse(xml_bytes)

    assert len(products) == 10
    assert all(p.store_id == "39" for p in products)
    by_code = {p.item_code: p for p in products}
    tomato = by_code["100"]
    assert tomato.name == "עגבניה"
    assert tomato.price == 2.9
    assert tomato.package_unit == "kg"


def test_rami_levy_maps_known_units():
    xml_bytes = (FIXTURES / "rami_levy_sample.xml").read_bytes()

    products = rami_levy.parse(xml_bytes)

    assert {p.package_unit for p in products} == {"g", "kg", "ml", "l", "unit"}


def test_rami_levy_wrong_store_id_raises():
    xml_bytes = (FIXTURES / "rami_levy_sample.xml").read_bytes().replace(
        b"<StoreId>39</StoreId>", b"<StoreId>999</StoreId>"
    )

    with pytest.raises(FeedValidationError):
        rami_levy.parse(xml_bytes)


def test_both_retailers_carry_matching_pasta_and_milk_items():
    """Both fixtures deliberately carry a pasta and a milk product findable by the same
    Hebrew search term at each retailer, so a single grocery-list request can find a real
    match at both — the original 5+5 items had no overlap at all, which made
    cross-retailer comparison untestable.

    Product *names* don't need to be byte-identical across retailers (CP9 follow-up,
    2026-08-08: each retailer's own real product naming is used instead — see
    tests/fixtures/feeds/{shufersal,rami_levy}_sample.xml's item_code/name comments), only
    that the shared search term (app/db/repositories.py's ILIKE substring match, driven by
    IngredientTranslation's search_name_he) appears in a product name at each retailer.
    """
    shufersal_products = shufersal.parse((FIXTURES / "shufersal_sample.xml").read_bytes())
    rami_levy_products = rami_levy.parse((FIXTURES / "rami_levy_sample.xml").read_bytes())

    shufersal_names = {p.name for p in shufersal_products}
    rami_levy_names = {p.name for p in rami_levy_products}

    for term in ("פסטה", "חלב"):
        assert any(term in name for name in shufersal_names), f"no shufersal product matches {term!r}"
        assert any(term in name for name in rami_levy_names), f"no rami_levy product matches {term!r}"
