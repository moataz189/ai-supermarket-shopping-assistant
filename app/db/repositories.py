import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import RetailerProduct

UNIT_TO_BASE = {"g": 1, "kg": 1000, "ml": 1, "l": 1000, "unit": 1}

_HEBREW_LETTERS = "א-ת"

# Safety valve on the raw SQL fetch, before the Python-side boundary filter (see
# _word_boundary_pattern) narrows it down -- not the real precision mechanism, just a
# bound against a pathological word matching thousands of rows. Generous on purpose.
_MAX_RAW_MATCHES = 500


def unit_price(price: float, package_size: float, package_unit: str) -> float:
    base_qty = package_size * UNIT_TO_BASE[package_unit]
    return price / base_qty if base_qty else price


def _hebrew_plural_singular_variant(word: str) -> str | None:
    """Hebrew's most common feminine-noun inflection: a singular ending in ה swaps with
    a plural ending in ות (e.g. קונכיה <-> קונכיות, "shell(s)"). Real user report
    (2026-08-14): our translated "pasta shells" query used the plural form, but a real
    Shufersal product used the singular ("פסטה ניוקטי סרדי קונכיה") -- a plain substring
    match can't bridge the two, since neither word is a substring of the other.

    Deliberately narrow: this swaps one specific, well-defined suffix for another
    complete word form -- it is not general stemming (which would match on a bare
    truncated prefix and risk pulling in unrelated words that merely start the same way).
    Returns None for words too short for the swap to be meaningful, and for words that
    don't end in either suffix at all."""
    if word.endswith("ות") and len(word) > 3:
        return word[:-2] + "ה"
    if word.endswith("ה") and len(word) > 2:
        return word[:-1] + "ות"
    return None


def _word_boundary_pattern(word: str) -> re.Pattern[str]:
    """Matches `word` only when it isn't fused directly onto another Hebrew letter (a
    different word) on either side. Real user report (2026-08-14): a plain
    `ILIKE '%חלב%'` ("milk") also matched חלבון/חלבה/חלבי/סחלב ("protein"/"halva"/
    "dairy [adj]"/"orchid") -- unrelated words that merely happen to contain the same
    three letters -- burying the ~20 genuine milk products among hundreds of false
    positives well past the retrieval limit, so the relevance filter downstream never
    saw them at all.

    Deliberately treats a transition from a Hebrew letter to *anything else* (a digit,
    punctuation, whitespace, or the string's own start/end) as a real word boundary, not
    only whitespace -- real user report (2026-08-16): retailer feeds routinely fuse a
    weight/count suffix directly onto the preceding word with no space at all (e.g.
    "קונכיה500גר", "טונה4*160ג") -- a whitespace-only boundary check (this function's
    previous, SQL-side implementation) missed these genuine matches entirely, while
    still correctly needing to exclude two Hebrew letters directly touching (סחלב) as
    fusion into a different word. Implemented in Python (not SQL) specifically so this
    distinction is checkable at all: portability across Postgres/SQLite already ruled
    out a DB-side regex/`\\y` word-boundary (see search_candidates), and plain
    space-delimited LIKE patterns can't express "boundary unless the next character is
    a Hebrew letter" either. This still won't catch every false positive (e.g. "ריבת
    חלב", dulce de leche -- "חלב" genuinely is its own word there, just the wrong
    product category); that's a semantic distinction left to product_relevance.py's LLM
    filter, which can only do its job once the real candidates actually make it into
    the pool this function returns."""
    escaped = re.escape(word)
    return re.compile(rf"(?<![{_HEBREW_LETTERS}]){escaped}(?![{_HEBREW_LETTERS}])")


def _matches_word(name: str, word: str) -> bool:
    """True if `word` (or its Hebrew plural/singular variant) appears in `name` as a
    genuine token per _word_boundary_pattern."""
    if _word_boundary_pattern(word).search(name):
        return True
    variant = _hebrew_plural_singular_variant(word)
    return bool(variant and _word_boundary_pattern(variant).search(name))


class ProductRepository:
    def __init__(self, session: Session):
        self.session = session

    def search_candidates(self, query: str, retailer: str, limit: int = 50) -> list[RetailerProduct]:
        # Each word of `query` must appear somewhere in the name (a separate condition per
        # word, ANDed) rather than the whole phrase as one contiguous substring -- real
        # user report (2026-08-14): the translated query "קונכיות פסטה" ("shells pasta")
        # never matched a real product named "...פסטה...קונכיות" ("...pasta...shells"),
        # since retailer product names don't reliably use the same word order a
        # translated multi-word ingredient name does.
        #
        # The SQL stage is a broad, plain substring pass per word (still ANDed) -- just
        # wide enough to bound the query, per _MAX_RAW_MATCHES. The actual word-boundary
        # precision (see _matches_word/_word_boundary_pattern, including the Hebrew
        # plural/singular variant) happens in Python afterward, since it needs
        # Hebrew-letter-vs-anything-else adjacency checks a portable SQL LIKE can't
        # express.
        #
        # Results are ordered shortest-name-first before the limit is applied -- real user
        # report (2026-08-14): with no ordering, a plain product ("עגבניה"/"בננה", tomato/
        # banana) was routinely arbitrary-sliced out of the results by whatever else
        # happened to match, while a much longer, unrelated compound product (crushed-
        # tomato puree, a banana-flavored snack) survived the cut. A shorter name
        # containing the same token is far more likely to *be* the plain base product
        # than a longer, more qualified/flavored one.
        words = query.split()
        stmt = select(RetailerProduct).where(RetailerProduct.retailer == retailer)
        for word in words:
            variant = _hebrew_plural_singular_variant(word)
            if variant:
                stmt = stmt.where(
                    or_(RetailerProduct.name.ilike(f"%{word}%"), RetailerProduct.name.ilike(f"%{variant}%"))
                )
            else:
                stmt = stmt.where(RetailerProduct.name.ilike(f"%{word}%"))
        stmt = stmt.limit(_MAX_RAW_MATCHES)
        raw = list(self.session.scalars(stmt))

        matched = [p for p in raw if all(_matches_word(p.name, word) for word in words)]
        matched.sort(key=lambda p: len(p.name))
        return matched[:limit]

    def get_product(self, retailer: str, item_code: str) -> RetailerProduct | None:
        stmt = select(RetailerProduct).where(
            RetailerProduct.retailer == retailer, RetailerProduct.item_code == item_code
        )
        return self.session.scalars(stmt).first()
