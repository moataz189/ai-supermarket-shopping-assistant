from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, RetailerFeedStatus, RetailerProduct
from app.ingestion.downloaders import DownloadedFeed, DownloadError
from app.ingestion.pipeline import FeedType
from app.ingestion.run import run_live

_SHUFERSAL_XML = """<Root>
  <StoreID>413</StoreID>
  <Items>
    <Item>
      <ItemCode>1</ItemCode>
      <ItemName>milk</ItemName>
      <ItemPrice>6.0</ItemPrice>
      <Quantity>1</Quantity>
      <UnitQty>ליטר</UnitQty>
    </Item>
  </Items>
</Root>""".encode()


class _FakeDownloader:
    def __init__(self, feed=None, error=None):
        self._feed = feed
        self._error = error

    def download_latest(self, feed_type):
        if self._error:
            raise self._error
        return self._feed


def test_one_retailer_failing_does_not_block_the_other(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    monkeypatch.setattr("app.ingestion.run.SessionLocal", session_factory)
    monkeypatch.setattr("app.ingestion.run.init_db", lambda: None)

    working_feed = DownloadedFeed(
        retailer="shufersal",
        feed_type=FeedType.PRICE_FULL,
        source_filename="PriceFull-ok.gz",
        source_timestamp=datetime(2026, 8, 11, tzinfo=timezone.utc),
        xml_bytes=_SHUFERSAL_XML,
    )
    fake_downloaders = {
        "shufersal": _FakeDownloader(feed=working_feed),
        "rami_levy": _FakeDownloader(error=DownloadError("rami_levy: portal unreachable")),
    }

    with patch("app.ingestion.run._DOWNLOADERS", fake_downloaders):
        result = run_live(FeedType.PRICE_FULL)

    # Overall result reflects the partial failure...
    assert result is False

    # ...but shufersal still made it into the database.
    with session_factory() as session:
        assert session.query(RetailerProduct).filter_by(retailer="shufersal").count() == 1
        status = session.get(RetailerFeedStatus, "shufersal")
        assert status.last_full_filename == "PriceFull-ok.gz"
        # rami_levy never got as far as writing anything.
        assert session.get(RetailerFeedStatus, "rami_levy") is None


def test_all_retailers_succeeding_returns_true(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    monkeypatch.setattr("app.ingestion.run.SessionLocal", session_factory)
    monkeypatch.setattr("app.ingestion.run.init_db", lambda: None)

    def make_feed(retailer, xml_bytes):
        return DownloadedFeed(
            retailer=retailer,
            feed_type=FeedType.PRICE_FULL,
            source_filename=f"PriceFull-{retailer}.gz",
            source_timestamp=datetime(2026, 8, 11, tzinfo=timezone.utc),
            xml_bytes=xml_bytes,
        )

    rami_levy_xml = """<Root>
      <StoreId>39</StoreId>
      <Items>
        <Item>
          <ItemCode>1</ItemCode>
          <ItemNm>milk</ItemNm>
          <ItemPrice>6.0</ItemPrice>
          <Quantity>1</Quantity>
          <UnitQty>ליטר</UnitQty>
        </Item>
      </Items>
    </Root>""".encode()

    fake_downloaders = {
        "shufersal": _FakeDownloader(feed=make_feed("shufersal", _SHUFERSAL_XML)),
        "rami_levy": _FakeDownloader(feed=make_feed("rami_levy", rami_levy_xml)),
    }

    with patch("app.ingestion.run._DOWNLOADERS", fake_downloaders):
        result = run_live(FeedType.PRICE_FULL)

    assert result is True
