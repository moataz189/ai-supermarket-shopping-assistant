from xml.etree import ElementTree as ET

from app.db.models import ONLINE_STORE_IDS
from app.ingestion.feeds import ParsedProduct
from app.ingestion.pipeline import FeedValidationError

UNIT_MAP = {
    "גרם": "g",
    "קילוגרם": "kg",
    "מיליליטר": "ml",
    "ליטר": "l",
    "יחידות": "unit",
}


def parse(xml_bytes: bytes) -> list[ParsedProduct]:
    root = ET.fromstring(xml_bytes)
    store_id = root.findtext("StoreID")
    if store_id != ONLINE_STORE_IDS["shufersal"]:
        raise FeedValidationError(
            f"shufersal: expected StoreID {ONLINE_STORE_IDS['shufersal']!r}, got {store_id!r}"
        )

    products = []
    for item in root.find("Items"):
        unit_qty = item.findtext("UnitQty")
        if unit_qty not in UNIT_MAP:
            raise FeedValidationError(f"shufersal: unrecognized UnitQty {unit_qty!r}")
        products.append(
            ParsedProduct(
                item_code=item.findtext("ItemCode"),
                name=item.findtext("ItemName"),
                price=float(item.findtext("ItemPrice")),
                package_size=float(item.findtext("Quantity")),
                package_unit=UNIT_MAP[unit_qty],
                store_id=store_id,
            )
        )
    return products
