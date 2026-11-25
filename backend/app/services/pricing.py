"""Price resolution with explicit source labeling (stored quote, else CSV last close)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import QuoteSnapshot
from app.exceptions import AnalyzerError
from app.providers.base import MarketDataProvider, format_bar_timestamp


@dataclass(frozen=True)
class PriceInfo:
    ticker: str
    price: float
    source: str  # "quote:<provider>" or "local_csv_last_close"
    as_of: str  # exchange timestamp / fetch time, or the last bar date
    is_realtime: bool
    fetched_at: datetime | None
    exchange_timestamp: datetime | None


def latest_quote(session: Session, ticker: str) -> QuoteSnapshot | None:
    return session.scalars(
        select(QuoteSnapshot)
        .where(QuoteSnapshot.ticker == ticker)
        .order_by(QuoteSnapshot.fetched_at.desc(), QuoteSnapshot.id.desc())
        .limit(1)
    ).first()


class PriceResolver:
    """Resolve the best locally available price. Never claims real-time."""

    def __init__(self, session: Session, csv_provider: MarketDataProvider) -> None:
        self._session = session
        self._csv = csv_provider

    def resolve(self, ticker: str) -> PriceInfo | None:
        snapshot = latest_quote(self._session, ticker)
        if snapshot is not None:
            stamp = snapshot.exchange_timestamp or snapshot.fetched_at
            return PriceInfo(
                ticker=ticker,
                price=snapshot.price,
                source=f"quote:{snapshot.provider}",
                as_of=stamp.isoformat(),
                is_realtime=False,
                fetched_at=snapshot.fetched_at,
                exchange_timestamp=snapshot.exchange_timestamp,
            )
        try:
            result = self._csv.fetch_ohlcv(ticker, interval="1d")
        except AnalyzerError:
            return None
        last = result.dataframe.iloc[-1]
        return PriceInfo(
            ticker=ticker,
            price=float(last["close"]),
            source="local_csv_last_close",
            as_of=format_bar_timestamp(pd.Timestamp(last["timestamp"])),
            is_realtime=False,
            fetched_at=None,
            exchange_timestamp=None,
        )
