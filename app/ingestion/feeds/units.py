"""Shared Hebrew UnitQty normalization for both retailers' feed parsers.

Real live feeds (confirmed 2026-08-11 against Shufersal StoreID 413 and Rami Levy StoreID
39) are far messier than either fixture assumed: the same physical unit shows up spelled
several different ways depending on which punctuation mark (gershayim ", geresh ', or none)
a given store's data entry used, and with/without spaces — e.g. "מ"ל", "מ'ל", "מל", and
"מ ל" are all "milliliter". `normalize_unit` strips that punctuation noise first, then looks
the normalized form up in one shared synonym table — so both parsers recognize the same set
of variants instead of maintaining two separately-incomplete lists.

A raw value that's still unrecognized after normalization (e.g. the literal "1", seen live —
almost certainly a retailer data-entry mistake, not a real unit) returns None; callers skip
that single item with a warning rather than aborting the whole feed over one bad row.
"""

_PUNCTUATION_STRIP = str.maketrans("", "", "\"'׳״ ")

_UNIT_SYNONYMS = {
    # kilogram — "לק\"ג" ("per kg") describes the same physical unit as ק"ג/קילו/קילוגרם,
    # just phrased as a per-unit price rather than a plain unit label.
    "קג": "kg",
    "קילו": "kg",
    "קילוגרם": "kg",
    "לקג": "kg",
    # gram
    "גרם": "g",
    # liter
    "ליטר": "l",
    # milliliter
    "מל": "ml",
    "מיליליטר": "ml",
    # count/unit
    "יח": "unit",
    "יחידה": "unit",
    "יחידות": "unit",
    # meter — not convertible with weight/volume, stored as plain metadata like "unit" is.
    "מטר": "m",
    "מטרים": "m",
    # centimeter — same non-convertible treatment as meter.
    "סמ": "cm",
}


def normalize_unit(raw_unit_qty: str) -> str | None:
    normalized = raw_unit_qty.translate(_PUNCTUATION_STRIP)
    return _UNIT_SYNONYMS.get(normalized)
