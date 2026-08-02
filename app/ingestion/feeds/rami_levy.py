from xml.etree import ElementTree as ET

from app.db.models import ONLINE_STORE_IDS
from app.ingestion.feeds import ParsedProduct
from app.ingestion.pipeline import FeedValidationError

UNIT_MAP = {
    "גרם": "g",
    'ק"ג': "kg",
    'מ"ל': "ml",
    "ליטר": "l",
    "יח'": "unit",
}


def parse(xml_bytes: bytes) -> list[ParsedProduct]:
    """Parse a Rami Levy price-transparency feed.

    The MVP only ever calls this with the latest PriceFull file (full
    catalog snapshot). The per-item XML schema is identical for the
    incremental Price feed, so this function needs no changes to support it
    later — only `app.ingestion.pipeline.ingest_retailer_feed` does.
    """
    root = ET.fromstring(xml_bytes)
    store_id = root.findtext("StoreId")
    if store_id != ONLINE_STORE_IDS["rami_levy"]:
        raise FeedValidationError(
            f"rami_levy: expected StoreId {ONLINE_STORE_IDS['rami_levy']!r}, got {store_id!r}"
        )

    products = []
    for item in root.find("Items"):
        unit_qty = item.findtext("UnitQty")
        if unit_qty not in UNIT_MAP:
            raise FeedValidationError(f"rami_levy: unrecognized UnitQty {unit_qty!r}")
        products.append(
            ParsedProduct(
                item_code=item.findtext("ItemCode"),
                name=item.findtext("ItemNm"),
                price=float(item.findtext("ItemPrice")),
                package_size=float(item.findtext("Quantity")),
                package_unit=UNIT_MAP[unit_qty],
                store_id=store_id,
            )
        )
    return products
