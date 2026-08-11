"""Live downloader for Shufersal's price-transparency portal (prices.shufersal.co.il).

Verified by hand against the real, live site (2026-08-11) — not guessed:
  - No login/auth of any kind; GET https://prices.shufersal.co.il/FileObject/UpdateCategory
    ?catID={1|2}&storeId=413 returns an HTML fragment containing exactly one
    <a href="https://pricesprodpublic.blob.core.windows.net/...">, a SAS-signed Azure Blob
    URL that's directly GET-able with no auth and expires after a few hours (never store
    it — always re-resolve from the listing).
  - catID: 1 = Price (hourly incremental delta), 2 = PriceFull (daily full snapshot).
  - storeId: found via the store dropdown's real options list — value "413" is literally
    labeled "413 - שופרסל ONLINE", confirming it matches this project's own
    ONLINE_STORE_IDS["shufersal"].
  - Filename convention: "{Price|PriceFull}<ChainID>-<SubChainID>-<StoreID>-<YYYYMMDD>-
    <HHMMSS>.gz", e.g. "PriceFull7290027600007-002-413-20260811-034000.gz".
  - The downloaded bytes are real gzip (unlike Rami Levy's disguised ZIP) containing one XML
    file whose schema already matches app/ingestion/feeds/shufersal.py's existing parser
    unchanged (StoreID, ItemCode, ItemName, ItemPrice, Quantity, UnitQty).
"""

import gzip
import html
import re
from datetime import datetime
from urllib.parse import urlparse

import httpx

from app.db.models import ONLINE_STORE_IDS
from app.ingestion.downloaders import DownloadedFeed, DownloadError
from app.ingestion.downloaders._retry import with_retries
from app.ingestion.pipeline import FeedType

BASE_URL = "https://prices.shufersal.co.il"
STORE_ID = ONLINE_STORE_IDS["shufersal"]
_CAT_ID = {FeedType.PRICE: "1", FeedType.PRICE_FULL: "2"}
_BLOB_HREF_RE = re.compile(r'href="([^"]*blob\.core\.windows\.net[^"]*)"')
_FILENAME_TIMESTAMP_RE = re.compile(r"-(\d{8})-(\d{6})\.gz$", re.IGNORECASE)


def _resolve_download_url(client: httpx.Client, feed_type: FeedType) -> str:
    response = with_retries(
        lambda: client.get(
            f"{BASE_URL}/FileObject/UpdateCategory",
            params={"catID": _CAT_ID[feed_type], "storeId": STORE_ID},
        )
    )
    response.raise_for_status()
    match = _BLOB_HREF_RE.search(response.text)
    if not match:
        raise DownloadError(
            f"shufersal: no {feed_type.value} file found for store {STORE_ID} "
            "(listing page returned no matching blob link)"
        )
    return html.unescape(match.group(1))


def _parse_timestamp(filename: str) -> datetime:
    match = _FILENAME_TIMESTAMP_RE.search(filename)
    if not match:
        raise DownloadError(f"shufersal: could not parse a timestamp out of filename {filename!r}")
    date_part, time_part = match.groups()
    # Naive on purpose: the filename doesn't specify a timezone (presumably the retailer's
    # own server-local time, unconfirmed) — used only for logging/observability, never
    # compared against another timestamp, so asserting a specific tzinfo here would claim
    # more certainty than the source data actually gives.
    return datetime.strptime(date_part + time_part, "%Y%m%d%H%M%S")  # noqa: DTZ007


def download_latest(feed_type: FeedType) -> DownloadedFeed:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        download_url = _resolve_download_url(client, feed_type)
        filename = urlparse(download_url).path.rsplit("/", 1)[-1]

        response = with_retries(lambda: client.get(download_url))
        response.raise_for_status()

    try:
        xml_bytes = gzip.decompress(response.content)
    except OSError as exc:
        raise DownloadError(f"shufersal: {filename} was not valid gzip: {exc}") from exc

    return DownloadedFeed(
        retailer="shufersal",
        feed_type=feed_type,
        source_filename=filename,
        source_timestamp=_parse_timestamp(filename),
        xml_bytes=xml_bytes,
    )
