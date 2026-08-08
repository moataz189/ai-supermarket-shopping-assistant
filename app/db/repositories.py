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

    def search_candidates(self, query: str, retailer: str, limit: int = 5) -> list[RetailerProduct]:
        stmt = (
            select(RetailerProduct)
            .where(RetailerProduct.retailer == retailer, RetailerProduct.name.ilike(f"%{query}%"))
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def get_product(self, retailer: str, item_code: str) -> RetailerProduct | None:
        stmt = select(RetailerProduct).where(
            RetailerProduct.retailer == retailer, RetailerProduct.item_code == item_code
        )
        return self.session.scalars(stmt).first()
