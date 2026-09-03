"""Shared retry policy for the ticketing sources' read-only HTTP calls.

Every collection failure between 2026-08-14 and 2026-09-02 was a single
transient 403 from the Cineplex gateway that cleared seconds later. Discovery
calls have no per-item error handling, so one blip aborts a whole chain and
fails the scheduled run.

Only GETs against the ticketing sites go through here, so a retry can never
duplicate a write. Supabase writes keep their own, deliberately more
conservative, policy in storage.py.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar
from urllib.error import HTTPError, URLError

T = TypeVar("T")

# 401 is deliberately absent: a rotated subscription key should fail fast and
# loudly rather than being retried into the job timeout.
RETRY_STATUSES = frozenset({403, 408, 429, 500, 502, 503, 504})
RETRY_DELAYS_SECONDS = (2.0, 6.0)
RETRY_AFTER_CAP_SECONDS = 30.0
DEFAULT_BUDGET_SECONDS = 120.0


class RetryBudget:
    """Caps the total time one source may spend asleep between retries.

    A collection makes hundreds of requests per source, so without a ceiling a
    source-wide outage would spend the whole 20-minute job timeout on backoff
    instead of letting the other chains finish. Each source keeps its own
    budget so one failing site can't disarm the others' retries.
    """

    def __init__(self, seconds: float = DEFAULT_BUDGET_SECONDS) -> None:
        self._initial = seconds
        self.remaining = seconds

    def reset(self) -> None:
        self.remaining = self._initial

    def spend(self, seconds: float) -> bool:
        """Sleep for `seconds` if the budget allows; False when it's spent."""
        if seconds > self.remaining:
            return False
        self.remaining -= seconds
        time.sleep(seconds)
        return True


def retry_after_seconds(
    error: HTTPError, cap: float = RETRY_AFTER_CAP_SECONDS
) -> float | None:
    raw = error.headers.get("Retry-After") if error.headers else None
    if not raw:
        return None
    try:
        return min(float(raw), cap)
    except ValueError:
        return None


def open_with_retry(
    perform: Callable[[], T],
    budget: RetryBudget,
    statuses: frozenset[int] = RETRY_STATUSES,
    delays: tuple[float, ...] = RETRY_DELAYS_SECONDS,
    retry_after_cap: float = RETRY_AFTER_CAP_SECONDS,
    before_attempt: Callable[[], None] | None = None,
) -> T:
    """Call `perform`, retrying transient gateway and network errors.

    `before_attempt` runs ahead of every attempt, including retries, so a
    source's rate limiter still applies to the retried request.
    """
    for delay in (*delays, None):
        if before_attempt is not None:
            before_attempt()
        try:
            return perform()
        except HTTPError as error:
            if error.code not in statuses or delay is None:
                raise
            if not budget.spend(retry_after_seconds(error, retry_after_cap) or delay):
                raise
        except (URLError, TimeoutError):
            # A reset connection, DNS blip or handshake failure: no response
            # came back, so nothing was observed to have happened server-side.
            if delay is None:
                raise
            if not budget.spend(delay):
                raise
    raise AssertionError("unreachable")
