"""Quote provider interface and freshness labeling.

Freshness policy:
    No provider used here guarantees real-time data, so `is_realtime` is never
    reported as true. We store two timestamps for every quote:
      - `fetched_at`: when this application received the response (UTC).
      - `exchange_timestamp`: the provider-reported time of the last trade, if any.
    The status is derived only from the gap between those two values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class Quote:
    """A single provider quote with both timestamps preserved."""

    ticker: str
    price: float
    provider: str
    fetched_at: datetime
    exchange_timestamp: datetime | None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None


@runtime_checkable
class QuoteProvider(Protocol):
    """Protocol for optional polled quote sources."""

    name: str

    def fetch_quote(self, ticker: str) -> Quote:
        """Fetch one quote or raise an AnalyzerError subclass."""
        ...


FreshnessStatus = Literal["unknown", "recent", "stale"]


@dataclass(frozen=True)
class FreshnessInfo:
    status: FreshnessStatus
    age_seconds: float | None
    is_realtime: bool
    note: str


def describe_freshness(
    exchange_timestamp: datetime | None,
    fetched_at: datetime,
    *,
    recent_minutes: int,
    now: datetime | None = None,
) -> FreshnessInfo:
    """Label how old a quote's trade time is, without ever claiming real-time.

    `age_seconds` is measured from the exchange timestamp to `now` (or to
    `fetched_at` when `now` is omitted).
    """
    if exchange_timestamp is None:
        return FreshnessInfo(
            status="unknown",
            age_seconds=None,
            is_realtime=False,
            note="Provider did not report a trade timestamp; data age is unknown.",
        )
    reference = now or fetched_at
    age = max(0.0, (reference - exchange_timestamp).total_seconds())
    status: FreshnessStatus = "recent" if age <= recent_minutes * 60 else "stale"
    return FreshnessInfo(
        status=status,
        age_seconds=age,
        is_realtime=False,
        note=(
            f"Last trade time reported by the provider is {int(age)} seconds old. "
            "This provider does not guarantee real-time delivery; markets may also be closed."
        ),
    )
