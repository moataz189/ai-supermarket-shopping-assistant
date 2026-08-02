from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedProduct:
    item_code: str
    name: str
    price: float
    package_size: float
    package_unit: str
    store_id: str
