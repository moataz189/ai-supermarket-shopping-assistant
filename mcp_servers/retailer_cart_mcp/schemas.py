from typing import Literal

from pydantic import BaseModel


class CartItemRequest(BaseModel):
    name: str
    item_code: str
    quantity: float
    # None (the default) means "no recipe-derived amount — legacy whole-unit request",
    # and adapters must behave exactly as before this field existed. Any other value
    # ("g", "kg", "unit", "large", ...) means `quantity` is a recipe's actual requested
    # amount in that unit, and adapters run it through the retailer-specific quantity
    # conversion in mcp_servers/retailer_cart_mcp/quantity.py instead.
    unit: str | None = None
    # The matched product's own package size/unit from the local catalog (e.g. 500 "g"
    # for a pasta box) -- None when unknown. Only meaningful together with `unit` being
    # a real weight/volume: lets an adapter buy enough whole packages to cover a
    # requested weight/volume instead of always assuming one package is enough (see
    # quantity.py's packages_needed).
    package_size: float | None = None
    package_unit: str | None = None


class CartItemResult(BaseModel):
    name: str
    item_code: str
    status: Literal["added", "not_found", "error", "quantity_conversion_required"]
    reason: str | None = None
    matched_by: Literal["item_code", "exact_name"] | None = None
    quantity_confirmed: float | None = None
    # Only populated when the request carried a real recipe unit (see CartItemRequest.unit
    # above) — None for ordinary grocery-list/weekly-shop items, exactly as before this
    # field existed. requested_* is what the recipe actually asked for; cart_* is what
    # actually ended up in the retailer's cart after that retailer's own selling-method/
    # increment rules were applied — the two are deliberately kept separate rather than
    # overwriting one with the other (spec: requested vs cart quantity must not collapse
    # into a single number, e.g. "400 g requested" vs "0.5 kg actually added").
    requested_quantity: float | None = None
    requested_unit: str | None = None
    cart_quantity: float | None = None
    cart_unit: str | None = None


class PrepareRetailerCartResponse(BaseModel):
    retailer: str
    added: list[CartItemResult]
    failed: list[CartItemResult]
    blocked: bool
    blocked_reason: str | None = None
    cart_url: str | None = None
