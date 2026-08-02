from pathlib import Path

import pytest

from app.ingestion.feeds import rami_levy, shufersal
from app.ingestion.pipeline import FeedValidationError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "feeds"


def test_shufersal_parses_real_sample_feed():
    xml_bytes = (FIXTURES / "shufersal_sample.xml").read_bytes()

    products = shufersal.parse(xml_bytes)

    assert len(products) == 5
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

    assert len(products) == 5
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
