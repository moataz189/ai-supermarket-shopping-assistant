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
