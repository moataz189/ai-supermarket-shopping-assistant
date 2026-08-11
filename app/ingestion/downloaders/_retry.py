import logging
import time
from collections.abc import Callable
from typing import TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Only network-level failures are retried (connection reset, timeout, DNS) — an HTTP error
# status or a malformed response is a real failure, not a transient one, and is left to the
# caller to raise as DownloadError.
_RETRYABLE_EXCEPTIONS = (httpx.TransportError, httpx.TimeoutException)


def with_retries(fn: Callable[[], T], *, attempts: int = 3, backoff_seconds: float = 2.0) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            if attempt < attempts:
                logger.warning(
                    "transient network failure (attempt %d/%d): %s", attempt, attempts, exc
                )
                time.sleep(backoff_seconds * attempt)
    raise last_exc  # type: ignore[misc]
