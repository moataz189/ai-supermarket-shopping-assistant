import logging
from xml.etree import ElementTree as ET

from app.db.models import ONLINE_STORE_IDS
from app.ingestion.feeds import ParsedProduct
from app.ingestion.feeds.units import normalize_unit
from app.ingestion.pipeline import FeedValidationError

logger = logging.getLogger(__name__)


def parse(xml_bytes: bytes) -> list[ParsedProduct]:
    """Parse a Rami Levy price-transparency feed (both PriceFull and Price share this same
    per-item schema — see app.ingestion.feeds.ParsedProduct)."""
    root = ET.fromstring(xml_bytes)
    store_id = root.findtext("StoreId")
    if store_id != ONLINE_STORE_IDS["rami_levy"]:
        raise FeedValidationError(
            f"rami_levy: expected StoreId {ONLINE_STORE_IDS['rami_levy']!r}, got {store_id!r}"
        )

    products = []
    for item in root.find("Items"):
        unit_qty = item.findtext("UnitQty")
        package_unit = normalize_unit(unit_qty)
        item_code = item.findtext("ItemCode")
        if package_unit is None:
            # One retailer's bad data entry (a genuinely unrecognized unit, not just a
            # punctuation variant already handled by normalize_unit) must not take down
            # ingestion of the rest of the feed.
            logger.warning(
                "rami_levy: skipping item_code=%s, unrecognized UnitQty=%r", item_code, unit_qty
            )
            continue
        products.append(
            ParsedProduct(
                item_code=item_code,
                name=item.findtext("ItemNm"),
                price=float(item.findtext("ItemPrice")),
                package_size=float(item.findtext("Quantity")),
                package_unit=package_unit,
                store_id=store_id,
            )
        )
    return products
