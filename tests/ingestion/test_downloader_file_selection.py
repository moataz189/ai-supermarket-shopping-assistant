import pytest

from app.ingestion.downloaders import DownloadError
from app.ingestion.downloaders import rami_levy as rami_levy_downloader
from app.ingestion.downloaders import shufersal as shufersal_downloader
from app.ingestion.pipeline import FeedType


class _FakeResponse:
    def __init__(self, text="", json_data=None):
        self.text = text
        self._json_data = json_data
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._json_data


class _FakeClient:
    """Minimal stand-in for httpx.Client — both downloader modules take `client` as an
    explicit parameter on their internal selection functions, so no HTTP mocking library or
    real network call is needed to test the "pick the right/latest file" logic in
    isolation."""

    def __init__(self, get_response=None, post_response=None):
        self._get_response = get_response
        self._post_response = post_response

    def get(self, *args, **kwargs):
        return self._get_response

    def post(self, *args, **kwargs):
        return self._post_response


def test_shufersal_resolves_and_unescapes_the_single_blob_link():
    html = (
        '<a href="https://pricesprodpublic.blob.core.windows.net/pricefull/'
        'PriceFull7290027600007-002-413-20260811-034000.gz?sv=2014-02-14&amp;sig=abc%3D">'
        "download</a>"
    )
    client = _FakeClient(get_response=_FakeResponse(text=html))

    url = shufersal_downloader._resolve_download_url(client, FeedType.PRICE_FULL)

    assert url == (
        "https://pricesprodpublic.blob.core.windows.net/pricefull/"
        "PriceFull7290027600007-002-413-20260811-034000.gz?sv=2014-02-14&sig=abc%3D"
    )


def test_shufersal_raises_when_no_blob_link_present():
    client = _FakeClient(get_response=_FakeResponse(text="<html><body>no results</body></html>"))

    with pytest.raises(DownloadError, match="no PriceFull file found"):
        shufersal_downloader._resolve_download_url(client, FeedType.PRICE_FULL)


def test_shufersal_parses_timestamp_from_filename():
    ts = shufersal_downloader._parse_timestamp("PriceFull7290027600007-002-413-20260811-034000.gz")
    assert (ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second) == (2026, 8, 11, 3, 40, 0)


def test_rami_levy_picks_the_lexicographically_latest_filename():
    file_page = '<meta name="csrftoken" content="tok123"/>'
    dir_json = {
        "aaData": [
            {"name": "pricefull7290058140886-039-202608090513.gz"},
            {"name": "pricefull7290058140886-039-202608110516.gz"},  # latest
            {"name": "pricefull7290058140886-039-202608100515.gz"},
        ]
    }
    client = _FakeClient(
        get_response=_FakeResponse(text=file_page), post_response=_FakeResponse(json_data=dir_json)
    )

    filename = rami_levy_downloader._latest_filename(client, FeedType.PRICE_FULL)

    assert filename == "pricefull7290058140886-039-202608110516.gz"


def test_rami_levy_raises_when_no_matching_file_found():
    file_page = '<meta name="csrftoken" content="tok123"/>'
    client = _FakeClient(
        get_response=_FakeResponse(text=file_page), post_response=_FakeResponse(json_data={"aaData": []})
    )

    with pytest.raises(DownloadError, match="no PriceFull file found"):
        rami_levy_downloader._latest_filename(client, FeedType.PRICE_FULL)


def test_rami_levy_search_terms_are_zero_padded_and_mutually_exclusive():
    # Store "39" must search as "-039" (the real filename convention) — confirmed live —
    # and PRICE_FULL's term must never accidentally match a PRICE (or promofull) filename.
    full_term = rami_levy_downloader._SEARCH_TERM[FeedType.PRICE_FULL]
    delta_term = rami_levy_downloader._SEARCH_TERM[FeedType.PRICE]
    assert full_term == "pricefull7290058140886-039"
    assert delta_term == "price7290058140886-039-"
    assert full_term not in "promofull7290058140886-039-202608110516.gz"
    assert delta_term not in "pricefull7290058140886-039-202608110516.gz"


def test_rami_levy_parses_timestamp_from_filename():
    ts = rami_levy_downloader._parse_timestamp("pricefull7290058140886-039-202608110516.gz")
    assert (ts.year, ts.month, ts.day, ts.hour, ts.minute) == (2026, 8, 11, 5, 16)
