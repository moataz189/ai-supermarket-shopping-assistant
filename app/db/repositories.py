from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import RetailerProduct

UNIT_TO_BASE = {"g": 1, "kg": 1000, "ml": 1, "l": 1000, "unit": 1}


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


def _word_token_conditions(word: str):
    """Matches `word` as a complete, space-delimited token in `RetailerProduct.name` --
    not merely a substring fused inside a longer word. Real user report (2026-08-14): a
    plain `ILIKE '%חלב%'` ("milk") also matched חלבון/חלבה/חלבי/סחלב ("protein"/"halva"/
    "dairy [adj]"/"orchid") -- unrelated words that merely happen to contain the same three
    letters -- burying the ~20 genuine milk products among hundreds of false positives well
    past the retrieval limit, so the relevance filter downstream never saw them at all.

    Four ilike patterns cover every position a token can occupy (whole name, leading,
    trailing, or interior), using plain space-delimited boundaries -- portable across
    Postgres and SQLite alike, unlike a DB-specific regex/`\\y` word-boundary (already
    ruled out for that reason -- see search_candidates). This still won't catch every
    false positive (e.g. "ריבת חלב", dulce de leche -- "חלב" genuinely is its own word
    there, just the wrong product category); that's a semantic distinction left to
    product_relevance.py's LLM filter, which can only do its job once the real candidates
    actually make it into the pool this function returns."""
    return or_(
        RetailerProduct.name.ilike(word),
        RetailerProduct.name.ilike(f"{word} %"),
        RetailerProduct.name.ilike(f"% {word}"),
        RetailerProduct.name.ilike(f"% {word} %"),
    )


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
        # Each word also tries its Hebrew plural/singular variant (see
        # _hebrew_plural_singular_variant) as an OR alternative -- real user report:
        # "קונכיות" (plural) never matched a real product's "קונכיה" (singular).
        #
        # Results are ordered shortest-name-first before the limit is applied -- real user
        # report (2026-08-14): with no ordering, a plain product ("עגבניה"/"בננה", tomato/
        # banana) was routinely arbitrary-sliced out of the results by whatever else
        # happened to match, while a much longer, unrelated compound product (crushed-
        # tomato puree, a banana-flavored snack) survived the cut. A shorter name
        # containing the same token is far more likely to *be* the plain base product
        # than a longer, more qualified/flavored one.
        stmt = select(RetailerProduct).where(RetailerProduct.retailer == retailer)
        for word in query.split():
            variant = _hebrew_plural_singular_variant(word)
            word_match = _word_token_conditions(word)
            if variant:
                word_match = or_(word_match, _word_token_conditions(variant))
            stmt = stmt.where(word_match)
        stmt = stmt.order_by(func.length(RetailerProduct.name)).limit(limit)
        return list(self.session.scalars(stmt))

    def get_product(self, retailer: str, item_code: str) -> RetailerProduct | None:
        stmt = select(RetailerProduct).where(
            RetailerProduct.retailer == retailer, RetailerProduct.item_code == item_code
        )
        return self.session.scalars(stmt).first()
