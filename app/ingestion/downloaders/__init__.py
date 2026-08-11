"""Live retailer price-feed downloaders — one module per retailer
(app/ingestion/downloaders/{shufersal,rami_levy}.py), each exposing a `download_latest`
function matching the `FeedDownloader` protocol below. Download logic (auth, file
discovery, decompression) is deliberately kept separate from parsing
(app/ingestion/feeds/*.py) and DB activation (app/ingestion/pipeline.py) — a downloader
only ever returns raw, already-decompressed XML bytes plus the source file's own metadata;
it never touches a database session or calls a parser.

Both retailers' actual live download mechanisms were reverse-engineered by hand against the
real, government-mandated price-transparency portals (not guessed) — see
docs/plan/15-live-price-ingestion.md for the full verified findings (login flow, file
listing API, exact filename conventions, and the fact that Rami Levy's ".gz" files are
actually ZIP archives despite the extension).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.ingestion.pipeline import FeedType


@dataclass(frozen=True)
class DownloadedFeed:
    retailer: str
    feed_type: FeedType
    source_filename: str
    source_timestamp: datetime
    xml_bytes: bytes


class DownloadError(Exception):
    """Raised for any live-download failure (network, auth, no matching file found) —
    callers (app/ingestion/run.py) catch this per retailer so one retailer's outage never
    blocks the other."""


class FeedDownloader(Protocol):
    def download_latest(self, feed_type: FeedType) -> DownloadedFeed: ...
