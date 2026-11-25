"""Offline tests for OHLCV schema normalization, CSV adapter, and Yahoo adapter."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yfinance as yf

from app.exceptions import (
    DataValidationError,
    EmptyDatasetError,
    InvalidRequestError,
    ProviderUnavailableError,
    SymbolNotFoundError,
)
from app.providers.csv_provider import CSVMarketDataProvider
from app.providers.normalizer import normalize_ohlcv_dataframe
from app.providers.yahoo_provider import YahooFinanceProvider


def test_normalizer_accepts_datetime_index_with_timezone_and_multiindex() -> None:
    """Verify yfinance-style tz-aware DatetimeIndex and MultiIndex columns normalize cleanly."""
    idx = pd.DatetimeIndex(
        ["2025-03-03 00:00:00-05:00", "2025-03-04 00:00:00-05:00"],
        name="Date",
    )
    columns = pd.MultiIndex.from_tuples(
        [
            ("Open", "AAPL"),
            ("High", "AAPL"),
            ("Low", "AAPL"),
            ("Close", "AAPL"),
            ("Volume", "AAPL"),
        ]
    )
    raw = pd.DataFrame(
        [
            [180.0, 183.5, 179.0, 182.0, 45_000_000],
            [182.0, 185.0, 181.0, 184.5, 48_000_000],
        ],
        index=idx,
        columns=columns,
    )

    normalized = normalize_ohlcv_dataframe(raw, ticker="AAPL")
    assert list(normalized.columns) == [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    assert normalized["timestamp"].dt.strftime("%Y-%m-%d").tolist() == [
        "2025-03-03",
        "2025-03-04",
    ]


def test_normalizer_rejects_missing_columns() -> None:
    raw = pd.DataFrame({"date": ["2025-01-02"], "open": [100.0], "close": [101.0]})
    with pytest.raises(DataValidationError) as exc_info:
        normalize_ohlcv_dataframe(raw, ticker="AAPL")
    assert "missing_columns" in exc_info.value.details
    assert "high" in exc_info.value.details["missing_columns"]


def test_normalizer_rejects_duplicate_timestamps() -> None:
    raw = pd.DataFrame(
        [
            {"date": "2025-01-02", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
            {"date": "2025-01-02", "open": 11, "high": 13, "low": 10, "close": 12, "volume": 200},
        ]
    )
    with pytest.raises(DataValidationError, match="duplicate timestamps"):
        normalize_ohlcv_dataframe(raw, ticker="AAPL")


@pytest.mark.parametrize(
    "bad_row,expected_msg",
    [
        (
            {"date": "not-a-date", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
            "unparseable timestamp",
        ),
        (
            {"date": "2025-01-02", "open": "abc", "high": 12, "low": 9, "close": 11, "volume": 100},
            "non-numeric",
        ),
        (
            {"date": "2025-01-02", "open": -5, "high": 12, "low": 9, "close": 11, "volume": 100},
            "strictly positive",
        ),
        (
            {"date": "2025-01-02", "open": 10, "high": 12, "low": 9, "close": 11, "volume": -1},
            "cannot contain negative",
        ),
        (
            {"date": "2025-01-02", "open": 10, "high": 8, "low": 9, "close": 8.5, "volume": 100},
            "invalid OHLC relationships",
        ),
        (
            {"date": "2025-01-02", "open": 15, "high": 12, "low": 9, "close": 11, "volume": 100},
            "invalid OHLC relationships",
        ),
    ],
)
def test_normalizer_rejects_corrupt_values_and_ohlc_violations(
    bad_row: dict[str, object], expected_msg: str
) -> None:
    raw = pd.DataFrame([bad_row])
    with pytest.raises(DataValidationError, match=expected_msg):
        normalize_ohlcv_dataframe(raw, ticker="AAPL")


def test_csv_provider_loads_and_resamples_intervals(temp_csv_dir: Path) -> None:
    provider = CSVMarketDataProvider(temp_csv_dir)
    daily = provider.fetch_ohlcv("demo", interval="1d")
    weekly = provider.fetch_ohlcv("demo", interval="1wk")
    monthly = provider.fetch_ohlcv("demo", interval="1mo")

    assert daily.source == "local_csv"
    assert daily.is_realtime is False
    assert daily.bar_count == 80
    assert weekly.bar_count < daily.bar_count
    assert monthly.bar_count < weekly.bar_count


def test_csv_provider_rejects_jagged_rows_and_path_traversal(temp_csv_dir: Path) -> None:
    jagged = temp_csv_dir / "JAGGED.csv"
    jagged.write_text(
        "date,open,high,low,close,volume\n2025-01-02,10,12,9,11,100,EXTRA_VALUE\n",
        encoding="utf-8",
    )
    provider = CSVMarketDataProvider(temp_csv_dir)

    with pytest.raises(DataValidationError, match="Malformed CSV row"):
        provider.fetch_ohlcv("JAGGED")

    with pytest.raises(InvalidRequestError):
        provider.fetch_ohlcv("../secret")

    with pytest.raises(SymbolNotFoundError):
        provider.fetch_ohlcv("MISSING")


def test_yahoo_provider_normalizes_and_handles_errors_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    class DummyTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def history(self, **kwargs: object) -> pd.DataFrame:
            captured_kwargs.update(kwargs)
            if self.symbol == "EMPTY":
                return pd.DataFrame()
            if self.symbol == "BROKEN":
                raise RuntimeError("Simulated upstream timeout")
            idx = pd.DatetimeIndex(["2025-02-03", "2025-02-04"], name="Date")
            return pd.DataFrame(
                {
                    "Open": [200.0, 202.0],
                    "High": [205.0, 206.0],
                    "Low": [199.0, 201.0],
                    "Close": [203.0, 205.0],
                    "Volume": [10_000_000, 12_000_000],
                },
                index=idx,
            )

    monkeypatch.setattr(yf, "Ticker", DummyTicker)
    provider = YahooFinanceProvider()

    res = provider.fetch_ohlcv(
        "msft",
        start_date=date(2025, 2, 3),
        end_date=date(2025, 2, 4),
        interval="1d",
    )
    assert res.ticker == "MSFT"
    assert res.source == "yahoo_finance_historical"
    assert res.is_realtime is False
    assert res.last_available_timestamp == "2025-02-04"
    # Verify end date passed to yfinance was incremented by +1 day for inclusive semantics.
    assert captured_kwargs["end"] == "2025-02-05"

    with pytest.raises(SymbolNotFoundError):
        provider.fetch_ohlcv("EMPTY")

    with pytest.raises(EmptyDatasetError):
        provider.fetch_ohlcv("EMPTY", start_date=date(2025, 1, 1), end_date=date(2025, 1, 10))

    with pytest.raises(ProviderUnavailableError):
        provider.fetch_ohlcv("BROKEN")
