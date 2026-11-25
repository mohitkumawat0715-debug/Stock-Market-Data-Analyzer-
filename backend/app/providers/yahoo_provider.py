"""Yahoo Finance historical OHLCV adapter built on yfinance.Ticker.history."""

from __future__ import annotations

from datetime import date, timedelta

import yfinance as yf

from app.exceptions import (
    AnalyzerError,
    EmptyDatasetError,
    InvalidRequestError,
    ProviderUnavailableError,
    SymbolNotFoundError,
)
from app.providers.base import MarketDataResult
from app.providers.csv_provider import SUPPORTED_INTERVALS, validate_ticker_symbol
from app.providers.normalizer import normalize_ohlcv_dataframe


class YahooFinanceProvider:
    """Historical market data adapter querying Yahoo Finance via yfinance."""

    SOURCE_LABEL = "yahoo_finance_historical"
    FRESHNESS_NOTE = (
        "Historical and delayed market data retrieved via Yahoo Finance (yfinance). "
        "Not real-time exchange data; subject to vendor delays, unannounced outages, "
        "and corporate-action revisions."
    )

    def fetch_ohlcv(
        self,
        ticker: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        interval: str = "1d",
    ) -> MarketDataResult:
        """Fetch historical OHLCV bars from Yahoo Finance and normalize to canonical schema."""
        clean_ticker = validate_ticker_symbol(ticker)
        if interval not in SUPPORTED_INTERVALS:
            raise InvalidRequestError(
                f"Unsupported interval '{interval}'. Supported intervals: 1d, 1wk, 1mo.",
                details={"interval": interval},
            )

        if start_date is not None and end_date is not None and start_date > end_date:
            raise InvalidRequestError(
                "start_date must be earlier than or equal to end_date.",
                details={
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                },
            )

        # Build yfinance.Ticker.history arguments. Note that yfinance treats 'end'
        # as an exclusive upper bound, so +1 calendar day includes end_date bars.
        history_kwargs: dict[str, object] = {
            "interval": interval,
            "auto_adjust": False,
            "actions": False,
        }
        if start_date is None and end_date is None:
            history_kwargs["period"] = "1y"
        else:
            effective_start = start_date or (
                end_date - timedelta(days=365) if end_date else None
            )
            if effective_start is not None:
                history_kwargs["start"] = effective_start.isoformat()
            if end_date is not None:
                history_kwargs["end"] = (end_date + timedelta(days=1)).isoformat()

        try:
            yf_ticker = yf.Ticker(clean_ticker)
            raw_df = yf_ticker.history(**history_kwargs)
        except AnalyzerError:
            raise
        except Exception as exc:
            raise ProviderUnavailableError(
                f"Yahoo Finance request failed for ticker '{clean_ticker}': {exc}",
                details={"ticker": clean_ticker, "provider": self.SOURCE_LABEL},
            ) from exc

        if raw_df is None or raw_df.empty:
            if start_date is None and end_date is None:
                raise SymbolNotFoundError(
                    f"Ticker '{clean_ticker}' returned no historical data from Yahoo Finance. "
                    "Verify that the symbol is valid and listed.",
                    details={"ticker": clean_ticker, "provider": self.SOURCE_LABEL},
                )
            raise EmptyDatasetError(
                f"Yahoo Finance returned zero OHLCV bars for '{clean_ticker}' in the requested window. "
                "The symbol may be unavailable, delisted, or outside trading dates.",
                details={
                    "ticker": clean_ticker,
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                    "provider": self.SOURCE_LABEL,
                },
            )

        normalized = normalize_ohlcv_dataframe(
            raw_df,
            ticker=clean_ticker,
            start_date=start_date,
            end_date=end_date,
        )

        return MarketDataResult(
            ticker=clean_ticker,
            interval=interval,
            source=self.SOURCE_LABEL,
            dataframe=normalized,
            freshness_note=self.FRESHNESS_NOTE,
            is_realtime=False,
        )
