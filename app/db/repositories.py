from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RetailerProduct

UNIT_TO_BASE = {"g": 1, "kg": 1000, "ml": 1, "l": 1000, "unit": 1}


def unit_price(price: float, package_size: float, package_unit: str) -> float:
    base_qty = package_size * UNIT_TO_BASE[package_unit]
    return price / base_qty if base_qty else price


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
        stmt = select(RetailerProduct).where(RetailerProduct.retailer == retailer)
        for word in query.split():
            stmt = stmt.where(RetailerProduct.name.ilike(f"%{word}%"))
        stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def get_product(self, retailer: str, item_code: str) -> RetailerProduct | None:
        stmt = select(RetailerProduct).where(
            RetailerProduct.retailer == retailer, RetailerProduct.item_code == item_code
        )
        return self.session.scalars(stmt).first()
