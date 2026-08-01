from datetime import datetime, timedelta, timezone

from app.db.models import RetailerFeedStatus
from app.ingestion.pipeline import is_stale


def test_not_stale_within_threshold():
    status = RetailerFeedStatus(
        retailer="shufersal",
        last_updated_at=datetime.now(timezone.utc) - timedelta(hours=1),
        stale=False,
    )

    assert is_stale(status, threshold_hours=48) is False


def test_stale_past_threshold():
    status = RetailerFeedStatus(
        retailer="shufersal",
        last_updated_at=datetime.now(timezone.utc) - timedelta(hours=49),
        stale=False,
    )

    assert is_stale(status, threshold_hours=48) is True


def test_stale_uses_default_48_hour_threshold():
    status = RetailerFeedStatus(
        retailer="rami_levy",
        last_updated_at=datetime.now(timezone.utc) - timedelta(hours=47),
        stale=False,
    )

    assert is_stale(status) is False
