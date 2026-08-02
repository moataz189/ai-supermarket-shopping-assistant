from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedProduct:
    """One parsed feed item — same shape for both PriceFull and Price feeds.

    Israeli price-transparency feeds publish this same per-item schema
    whether the file is a PriceFull (full catalog) or Price (delta) feed;
    only the *set* of items differs (all products vs. only changed ones),
    so retailer parsers don't need to change to support Price feeds later —
    see `app.ingestion.pipeline.FeedType`.
    """

    item_code: str
    name: str
    price: float
    package_size: float
    package_unit: str
    store_id: str
