import argparse
import logging
import sys
from pathlib import Path

from app.db.session import SessionLocal, init_db
from app.ingestion.downloaders import DownloadError, FeedDownloader
from app.ingestion.downloaders import rami_levy as rami_levy_downloader
from app.ingestion.downloaders import shufersal as shufersal_downloader
from app.ingestion.feeds import rami_levy, shufersal
from app.ingestion.pipeline import (
    FeedType,
    FeedValidationError,
    already_processed,
    ingest_retailer_feed,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "feeds"

logger = logging.getLogger(__name__)

_PARSERS = {"shufersal": shufersal.parse, "rami_levy": rami_levy.parse}
_DOWNLOADERS: dict[str, FeedDownloader] = {
    "shufersal": shufersal_downloader,
    "rami_levy": rami_levy_downloader,
}


def load_fixtures() -> None:
    """Load each retailer's latest PriceFull fixture (full catalog snapshot) — local
    dev/tests only, unrelated to (and unaffected by) the live downloaders below."""
    init_db()
    with SessionLocal() as session:
        shufersal_xml = (FIXTURES_DIR / "shufersal_sample.xml").read_bytes()
        ingest_retailer_feed(
            session, "shufersal", shufersal.parse(shufersal_xml), feed_type=FeedType.PRICE_FULL
        )

        rami_levy_xml = (FIXTURES_DIR / "rami_levy_sample.xml").read_bytes()
        ingest_retailer_feed(
            session, "rami_levy", rami_levy.parse(rami_levy_xml), feed_type=FeedType.PRICE_FULL
        )


def run_live(feed_type: FeedType) -> bool:
    """Download and ingest the latest live feed of `feed_type` for every retailer,
    independently — one retailer's failure (network, auth, validation) is logged and
    skipped, never allowed to stop the other. Returns True iff every retailer succeeded
    (including "already processed, nothing to do"), so the caller can set a non-zero exit
    code on partial failure without that failure being silent.
    """
    init_db()
    all_ok = True

    for retailer, downloader in _DOWNLOADERS.items():
        try:
            feed = downloader.download_latest(feed_type)

            # Deliberately separate session scopes, not one shared session: `already_processed`
            # (a plain read) and `ingest_retailer_feed` (which opens its own explicit
            # `session.begin()`) would otherwise conflict — SQLAlchemy 2.0 autobegins a
            # transaction on the first `session.get()` inside `already_processed`, and a
            # second explicit `session.begin()` on that same still-open session then raises
            # "A transaction is already begun on this Session."
            with SessionLocal() as check_session:
                if already_processed(check_session, retailer, feed_type, feed.source_filename):
                    logger.info(
                        "retailer=%s feed_type=%s source_filename=%s result=skipped_duplicate",
                        retailer,
                        feed_type.value,
                        feed.source_filename,
                    )
                    continue

            parsed_products = _PARSERS[retailer](feed.xml_bytes)
            with SessionLocal() as session:
                ingest_retailer_feed(
                    session,
                    retailer,
                    parsed_products,
                    feed_type=feed_type,
                    source_filename=feed.source_filename,
                )

            logger.info(
                "retailer=%s feed_type=%s source_filename=%s source_timestamp=%s "
                "item_count=%d result=success",
                retailer,
                feed_type.value,
                feed.source_filename,
                feed.source_timestamp.isoformat(),
                len(parsed_products),
            )
        except (DownloadError, FeedValidationError) as exc:
            # Never logs feed.xml_bytes or any request/auth details — DownloadError/
            # FeedValidationError messages are already scoped to filenames/counts, not
            # credentials (rami_levy.py's login never puts the (public, passwordless)
            # credentials into an exception message either).
            all_ok = False
            logger.error(
                "retailer=%s feed_type=%s result=failed error=%s", retailer, feed_type.value, exc
            )
        except Exception:
            all_ok = False
            logger.exception(
                "retailer=%s feed_type=%s result=failed error=unexpected", retailer, feed_type.value
            )

    return all_ok


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["fixtures", "live-full", "live-delta"], required=True)
    args = parser.parse_args()

    if args.source == "fixtures":
        load_fixtures()
        return

    feed_type = FeedType.PRICE_FULL if args.source == "live-full" else FeedType.PRICE
    if not run_live(feed_type):
        sys.exit(1)


if __name__ == "__main__":
    main()
