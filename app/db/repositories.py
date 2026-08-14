from sqlalchemy import or_, select
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


class ProductRepository:
    def __init__(self, session: Session):
        self.session = session

    def search_candidates(self, query: str, retailer: str, limit: int = 30) -> list[RetailerProduct]:
        # Each word of `query` must appear somewhere in the name (a separate ILIKE per
        # word, ANDed) rather than the whole phrase as one contiguous substring -- real
        # user report (2026-08-14): the translated query "קונכיות פסטה" ("shells pasta")
        # never matched a real product named "...פסטה...קונכיות" ("...pasta...shells"),
        # since retailer product names don't reliably use the same word order a
        # translated multi-word ingredient name does. limit raised from 5 to 30 for the
        # same underlying reason: with no ORDER BY, the previous 5-row cap returned an
        # arbitrary slice of whatever matched (confirmed live against real data --
        # Shufersal's first 5 "שום"/garlic matches were all garlic-*seasoned* cheese or
        # unrelated products, out of 116 total matches), so the relevance filter
        # downstream never got a real chance to find the genuine match among them. Still
        # a plain substring match per word, not a ranked/fuzzy search -- semantic
        # correctness is judged downstream by product_relevance.py, not here.
        #
        # Each word also tries its Hebrew plural/singular variant (see
        # _hebrew_plural_singular_variant) as an OR alternative -- real user report:
        # "קונכיות" (plural) never matched a real product's "קונכיה" (singular).
        stmt = select(RetailerProduct).where(RetailerProduct.retailer == retailer)
        for word in query.split():
            variant = _hebrew_plural_singular_variant(word)
            if variant:
                stmt = stmt.where(
                    or_(RetailerProduct.name.ilike(f"%{word}%"), RetailerProduct.name.ilike(f"%{variant}%"))
                )
            else:
                stmt = stmt.where(RetailerProduct.name.ilike(f"%{word}%"))
        stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def get_product(self, retailer: str, item_code: str) -> RetailerProduct | None:
        stmt = select(RetailerProduct).where(
            RetailerProduct.retailer == retailer, RetailerProduct.item_code == item_code
        )
        return self.session.scalars(stmt).first()
