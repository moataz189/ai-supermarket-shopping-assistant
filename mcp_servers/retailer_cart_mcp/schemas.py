from typing import Literal

from pydantic import BaseModel


class CartItemRequest(BaseModel):
    name: str
    item_code: str
    quantity: float


class CartItemResult(BaseModel):
    name: str
    item_code: str
    status: Literal["added", "not_found", "error"]
    reason: str | None = None
    matched_by: Literal["item_code", "exact_name", "name_fallback"] | None = None
    quantity_confirmed: float | None = None


class PrepareRetailerCartResponse(BaseModel):
    retailer: str
    added: list[CartItemResult]
    failed: list[CartItemResult]
    blocked: bool
    blocked_reason: str | None = None
    cart_url: str | None = None
