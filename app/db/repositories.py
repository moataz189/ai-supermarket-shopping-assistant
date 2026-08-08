from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IngredientTranslation, RetailerProduct

UNIT_TO_BASE = {"g": 1, "kg": 1000, "ml": 1, "l": 1000, "unit": 1}

# Already-verified-correct translations, seeded at startup so these never need an LLM
# call at all — see IngredientTranslation's docstring. Singular, generic form throughout
# (confirmed live: the real catalog lists produce singular — "עגבניה", not "עגבניות").
SEED_INGREDIENT_TRANSLATIONS: dict[str, str] = {
    "milk": "חלב",
    "oat milk": "חלב שיבולת שועל",
    "eggs": "ביצים",
    "tomatoes": "עגבניה",
    "onion": "בצל",
    "olive oil": "שמן זית",
}


def canonicalize_ingredient_name(name: str) -> str:
    return name.strip().lower()


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


class IngredientTranslationRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_many(self, canonical_names: list[str]) -> dict[str, IngredientTranslation]:
        if not canonical_names:
            return {}
        stmt = select(IngredientTranslation).where(
            IngredientTranslation.canonical_name.in_(canonical_names)
        )
        return {row.canonical_name: row for row in self.session.scalars(stmt)}

    def save_many(self, entries: list[tuple[str, str, str]]) -> None:
        """`entries`: (canonical_name, original_name, search_name_he) tuples — callers
        are expected to have already filtered to genuine cache misses (see get_many), so
        this always inserts rather than upserting."""
        if not entries:
            return
        now = datetime.now(timezone.utc)
        self.session.add_all([
            IngredientTranslation(
                canonical_name=canonical_name, original_name=original_name,
                search_name_he=search_name_he, created_at=now,
            )
            for canonical_name, original_name, search_name_he in entries
        ])
        self.session.commit()


def seed_ingredient_translations(session: Session) -> None:
    """Idempotent — only inserts seed entries not already present, so this is safe to
    call on every backend startup regardless of whether it's run before."""
    repo = IngredientTranslationRepository(session)
    canonical_seeds = {
        canonicalize_ingredient_name(name): (name, he)
        for name, he in SEED_INGREDIENT_TRANSLATIONS.items()
    }
    existing = repo.get_many(list(canonical_seeds))
    new_entries = [
        (canonical, name, he)
        for canonical, (name, he) in canonical_seeds.items()
        if canonical not in existing
    ]
    repo.save_many(new_entries)
