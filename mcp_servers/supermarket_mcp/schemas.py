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
    listed_in_feed: bool
    last_updated_at: str
    stale: bool


class GetIngredientTranslationsResponse(BaseModel):
    # Requested name -> Hebrew catalog search term; only names actually found in the
    # cache appear here (a miss is simply absent, not an error).
    translations: dict[str, str]


class IngredientTranslationEntry(BaseModel):
    name: str
    search_name_he: str
