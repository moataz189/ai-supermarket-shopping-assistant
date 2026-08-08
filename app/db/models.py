from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ONLINE_STORE_IDS = {"shufersal": "413", "rami_levy": "39"}


class Base(DeclarativeBase):
    pass


class RetailerProduct(Base):
    __tablename__ = "retailer_products"
    __table_args__ = (UniqueConstraint("retailer", "item_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    retailer: Mapped[str] = mapped_column(String(32), index=True)  # "shufersal" | "rami_levy"
    store_id: Mapped[str] = mapped_column(String(16))  # ONLINE_STORE_IDS[retailer]
    item_code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(256))
    category: Mapped[str] = mapped_column(String(128))
    package_size: Mapped[float] = mapped_column(Float)
    package_unit: Mapped[str] = mapped_column(String(16))  # g|kg|ml|l|unit
    price: Mapped[float] = mapped_column(Float)
    listed_in_feed: Mapped[bool] = mapped_column(Boolean, default=True)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime)


class RetailerFeedStatus(Base):
    __tablename__ = "retailer_feed_status"

    retailer: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)


class IngredientTranslation(Base):
    """Persistent cache of English recipe-ingredient name -> Hebrew supermarket-catalog
    search term (CP9 follow-up, 2026-08-08). Real Shufersal/Rami Levy catalogs are
    Hebrew-only, independent of what language a given conversation is in — this is a
    dedicated, retailer-agnostic search term, separate from `ParsedItem.display_name`
    (the user-facing label, which does follow the conversation's language).

    Populated two ways: a small set of already-verified-correct terms seeded at startup
    (`seed_ingredient_translations`), and on-demand via the LLM
    (`app/agent/ingredient_translation.py`) the first time a genuinely new ingredient is
    seen — written back here so the LLM is never asked to translate the same ingredient
    twice."""

    __tablename__ = "ingredient_translations"

    # Normalized (stripped, lowercased) English name — the cache key. Deliberately not
    # the raw `original_name` itself, so "Heavy Cream" and "heavy cream" share one entry.
    canonical_name: Mapped[str] = mapped_column(String(256), primary_key=True)
    original_name: Mapped[str] = mapped_column(String(256))  # exact string as first seen
    search_name_he: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime)
