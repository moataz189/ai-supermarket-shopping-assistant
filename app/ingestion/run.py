import argparse
from pathlib import Path

from app.db.session import SessionLocal, init_db
from app.ingestion.feeds import rami_levy, shufersal
from app.ingestion.pipeline import FeedType, ingest_retailer_feed

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "feeds"


def load_fixtures() -> None:
    """Load each retailer's latest PriceFull fixture (full catalog snapshot).

    `ingest_retailer_feed` also supports `FeedType.PRICE` (incremental delta
    upserts) — CP11's hourly CronJob calls it directly per downloaded `Price`
    file. There is no separate scheduler/CLI mode for that yet; this CLI's
    only job today is the one-shot `PriceFull` fixture bootstrap.
    """
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["fixtures"], required=True)
    args = parser.parse_args()

    if args.source == "fixtures":
        load_fixtures()


if __name__ == "__main__":
    main()
