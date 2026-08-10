from pydantic import BaseModel


class ProductCandidate(BaseModel):
    item_code: str
    name: str
    price: float


class SearchProductResponse(BaseModel):
    candidates: list[ProductCandidate]


class ProductPriceResponse(BaseModel):
    retailer: str
    store_id: str
    item_code: str
    name: str
    price: float
    unit_price: float
    package_size: float
    package_unit: str
    listed_in_feed: bool
    last_updated_at: str
    stale: bool
