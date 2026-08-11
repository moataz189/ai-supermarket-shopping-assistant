import pytest

from app.ingestion.feeds.units import normalize_unit


@pytest.mark.parametrize(
    "raw,expected",
    [
        # kilogram — every spelling/punctuation variant confirmed live across both retailers.
        ('ק"ג', "kg"),
        ("קילו", "kg"),
        ("קילוגרם", "kg"),
        ('לק"ג', "kg"),
        # gram
        ("גרם", "g"),
        # liter
        ("ליטר", "l"),
        # milliliter
        ('מ"ל', "ml"),
        ("מ'ל", "ml"),
        ("מל", "ml"),
        ("מיליליטר", "ml"),
        # count/unit
        ("יח'", "unit"),
        ("יח", "unit"),
        ("יחידה", "unit"),
        ("יחידות", "unit"),
        # length
        ("מטר", "m"),
        ("מטרים", "m"),
        ('ס"מ', "cm"),
    ],
)
def test_normalizes_known_variants(raw, expected):
    assert normalize_unit(raw) == expected


def test_unrecognized_unit_returns_none():
    # Confirmed live in a real Rami Levy feed — almost certainly a retailer data-entry
    # mistake, not a real unit; callers skip the item rather than treating this as "ml".
    assert normalize_unit("1") is None


def test_spacing_variant_normalizes_the_same_as_no_space():
    assert normalize_unit("מ ל") == normalize_unit("מל") == "ml"
