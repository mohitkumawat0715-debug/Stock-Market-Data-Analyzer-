"""Vendor-neutral interface for historical OHLCV market data providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

import pandas as pd


def format_bar_timestamp(ts: pd.Timestamp) -> str:
    """Format midnight timestamps as YYYY-MM-DD and intraday ones as ISO-8601."""
    if ts.hour == 0 and ts.minute == 0 and ts.second == 0 and ts.microsecond == 0:
        return ts.strftime("%Y-%m-%d")
    return ts.isoformat()


@dataclass(frozen=True)
class MarketDataResult:
    """Normalized market dataset bundled with explicit source and latency metadata."""

    ticker: str
    interval: str
    source: str
    dataframe: pd.DataFrame
    freshness_note: str
    is_realtime: bool = False

    @property
    def last_available_timestamp(self) -> str:
        """Return the formatted timestamp of the most recent bar in the dataset."""
        latest_ts = pd.Timestamp(self.dataframe["timestamp"].iloc[-1])
        return format_bar_timestamp(latest_ts)

    @property
    def bar_count(self) -> int:
        """Return total number of validated bars."""
        return int(len(self.dataframe))


@runtime_checkable
class MarketDataProvider(Protocol):
    """Protocol implemented by all historical OHLCV data adapters."""

    def fetch_ohlcv(
        self,
        ticker: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        interval: str = "1d",
    ) -> MarketDataResult:
        """Fetch, validate, and normalize OHLCV bars for a ticker and date window."""
        ...
