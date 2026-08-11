"""Live downloader for Rami Levy's price-transparency feed, published via a shared,
third-party "Cerberus Web Client" FTP-over-HTTP portal (not a Rami Levy-specific site) at
https://url.retail.publishedprices.co.il — the exact URL Rami Levy's own official
price-transparency page (rami-levy.co.il/he/price-transparency) directs users to.

Verified by hand against the real, live portal (2026-08-11) — not guessed:
  - Login: GET /login to obtain a session cookie (cftpSID) and a CSRF token (the page's
    <meta name="csrftoken">). POST /login/user with username="RamiLevi", password="" (the
    credentials Rami Levy's own page publishes — a public, intentionally passwordless
    account), and the CSRF token **as a form field named "csrftoken"** (confirmed from the
    portal's own common.min.js: it appends this exact hidden field to every form on submit —
    a header does not work, only the form field does). A successful login responds
    HTTP 302 to /file; a failed CSRF check responds HTTP 200 with the login form re-rendered
    and a "CSRF security check failed" status message.
  - File listing: POST /file/json/dir (a DataTables server-side-processing endpoint) with a
    fresh CSRF token (fetched from GET /file post-login — the login response's own token is
    not reused), `cd` (current directory, "" = root), and `sSearch` to filter by filename
    substring server-side. Response JSON: {"aaData": [{"name": ..., "size": ..., "time":
    ...}, ...], "iTotalDisplayRecords": ...}.
  - Filename convention for StoreID 039 specifically (Rami Levy Online — confirmed via the
    portal's own "Stores" metadata file, StoreName "מרלוג אינטרנט", StoreType 2) differs from
    physical branches': lowercase "pricefull<ChainID>-039-<YYYYMMDDHHMM>.gz" (daily) and
    "price<ChainID>-039-<YYYYMMDDHHMM>.gz" (hourly delta) — no separate date/time segment,
    no SubChainID segment, unlike physical branches' "Price<ChainID>-<Sub>-<Store>-<Date>-
    <Time>.gz". "latest" is simply the lexicographically-greatest filename, since the
    trailing YYYYMMDDHHMM sorts correctly as chronological order.
  - Download: GET /file/d/<filename> with the authenticated session cookie — no signed URL,
    no separate token.
  - **The downloaded bytes are a ZIP archive, not gzip, despite the ".gz" filename
    extension** — confirmed via `file`, containing exactly one XML entry named like
    "PriceFull7290058140886-039-202608110516.xml" (properly cased). That XML's schema
    already matches app/ingestion/feeds/rami_levy.py's existing parser unchanged (StoreId,
    ChainId, SubChainId, ItemNm, ManufacturerName, PriceUpdateDate) — physical branches use a
    materially different schema (StoreID, ItemName, ManufactureName, PriceUpdateTime), but
    this project only ever ingests StoreID 39, so that difference is irrelevant here.
  - **TLS quirk on the retailer's own side, confirmed live**: this exact host
    (url.retail.publishedprices.co.il) presents a certificate valid for
    "*.publishedprices.co.il"/"publishedprices.co.il" only — one subdomain level short of
    the three-level host Rami Levy's own price-transparency page links to. A plain
    `httpx.Client()` fails every request here with CERTIFICATE_VERIFY_FAILED /
    "Hostname mismatch". `_ssl_context_without_hostname_check` below keeps full
    certificate-chain/CA validation (`CERT_REQUIRED`) and only disables the exact-hostname
    check — a deliberate, narrow relaxation of this one known, verified mismatch, not a
    blanket `verify=False` (which would also silently accept an untrusted/self-signed cert).
"""

import io
import re
import ssl
import zipfile
from datetime import datetime

import httpx

from app.db.models import ONLINE_STORE_IDS
from app.ingestion.downloaders import DownloadedFeed, DownloadError
from app.ingestion.downloaders._retry import with_retries
from app.ingestion.pipeline import FeedType

BASE_URL = "https://url.retail.publishedprices.co.il"
USERNAME = "RamiLevi"
STORE_ID = ONLINE_STORE_IDS["rami_levy"]
CHAIN_ID = "7290058140886"


def _ssl_context_without_hostname_check() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED
    return context

# Filenames zero-pad the store number to 3 digits ("-039-"), unlike ONLINE_STORE_IDS
# ["rami_levy"] ("39" unpadded, which is what the XML content's own <StoreId> element
# actually contains — a real, confirmed difference between the filename convention and the
# XML content). "pricefull<chain>-039" never matches a "promofull..." filename (different
# prefix entirely), and "price<chain>-039-" never matches "pricefull<chain>-039-" either
# (the latter has "full" between "price" and the chain id) — both searches are unambiguous
# substring matches, confirmed against the real listing.
_PADDED_STORE_ID = STORE_ID.zfill(3)
_SEARCH_TERM = {
    FeedType.PRICE_FULL: f"pricefull{CHAIN_ID}-{_PADDED_STORE_ID}",
    FeedType.PRICE: f"price{CHAIN_ID}-{_PADDED_STORE_ID}-",
}
_CSRF_RE = re.compile(r'name="csrftoken" content="([^"]+)"')
_FILENAME_TIMESTAMP_RE = re.compile(r"-(\d{12})\.gz$", re.IGNORECASE)


def _csrf_token(response: httpx.Response) -> str:
    match = _CSRF_RE.search(response.text)
    if not match:
        raise DownloadError("rami_levy: could not find a csrftoken on the portal page")
    return match.group(1)


def _login(client: httpx.Client) -> None:
    login_page = with_retries(lambda: client.get(f"{BASE_URL}/login"))
    login_page.raise_for_status()
    token = _csrf_token(login_page)

    response = with_retries(
        lambda: client.post(
            f"{BASE_URL}/login/user",
            data={"username": USERNAME, "password": "", "r": "", "csrftoken": token},
        )
    )
    # The client follows redirects automatically (follow_redirects=True), so
    # response.status_code is the *final* page's status (200), not the login POST's own —
    # a successful login is a 302 to /file, which shows up in response.history instead.
    if not any(r.status_code == 302 for r in response.history):
        raise DownloadError(
            f"rami_levy: login failed (expected an HTTP 302 redirect, got {response.status_code} "
            "with no redirect in history) — the portal's login form or CSRF handling may have changed"
        )


def _latest_filename(client: httpx.Client, feed_type: FeedType) -> str:
    file_page = with_retries(lambda: client.get(f"{BASE_URL}/file"))
    file_page.raise_for_status()
    token = _csrf_token(file_page)

    response = with_retries(
        lambda: client.post(
            f"{BASE_URL}/file/json/dir",
            data={
                "cd": "",
                "sEcho": "1",
                "iColumns": "1",
                "iDisplayStart": "0",
                "iDisplayLength": "1000",
                "iSortingCols": "0",
                "sSearch": _SEARCH_TERM[feed_type],
                "csrftoken": token,
            },
        )
    )
    response.raise_for_status()
    data = response.json()
    names = [row["name"] for row in data.get("aaData", [])]
    if not names:
        raise DownloadError(
            f"rami_levy: no {feed_type.value} file found for store {STORE_ID} in the live listing"
        )
    return max(names)  # trailing YYYYMMDDHHMM sorts lexicographically == chronologically


def _parse_timestamp(filename: str) -> datetime:
    match = _FILENAME_TIMESTAMP_RE.search(filename)
    if not match:
        raise DownloadError(f"rami_levy: could not parse a timestamp out of filename {filename!r}")
    # Naive on purpose — see shufersal.py's _parse_timestamp for why.
    return datetime.strptime(match.group(1), "%Y%m%d%H%M")  # noqa: DTZ007


def _extract_single_xml(zip_bytes: bytes, filename: str) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            entries = archive.namelist()
            if len(entries) != 1:
                raise DownloadError(
                    f"rami_levy: expected exactly one file inside {filename}, found {entries}"
                )
            return archive.read(entries[0])
    except zipfile.BadZipFile as exc:
        raise DownloadError(f"rami_levy: {filename} was not a valid ZIP archive: {exc}") from exc


def download_latest(feed_type: FeedType) -> DownloadedFeed:
    with httpx.Client(
        timeout=30.0, follow_redirects=True, verify=_ssl_context_without_hostname_check()
    ) as client:
        _login(client)
        filename = _latest_filename(client, feed_type)

        response = with_retries(lambda: client.get(f"{BASE_URL}/file/d/{filename}"))
        response.raise_for_status()

    xml_bytes = _extract_single_xml(response.content, filename)

    return DownloadedFeed(
        retailer="rami_levy",
        feed_type=feed_type,
        source_filename=filename,
        source_timestamp=_parse_timestamp(filename),
        xml_bytes=xml_bytes,
    )
