"""Local CSV market data adapter for deterministic offline execution and testing."""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

import pandas as pd

from app.exceptions import (
    DataValidationError,
    EmptyDatasetError,
    InvalidRequestError,
    SymbolNotFoundError,
)
from app.providers.base import MarketDataResult
from app.providers.normalizer import normalize_ohlcv_dataframe

TICKER_PATTERN = re.compile(r"^[A-Za-z0-9.\-]{1,12}$")
SUPPORTED_INTERVALS = {"1d", "1wk", "1mo"}


def validate_ticker_symbol(ticker: str) -> str:
    """Validate and uppercase a ticker symbol, blocking path traversal tokens."""
    cleaned = ticker.strip().upper()
    if not cleaned or not TICKER_PATTERN.fullmatch(cleaned) or ".." in cleaned:
        raise InvalidRequestError(
            f"Invalid ticker symbol '{ticker}'. Expected 1-12 alphanumeric characters, dots, or hyphens.",
            details={"ticker": ticker},
        )
    return cleaned


def _resample_ohlcv(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Aggregate canonical daily OHLCV bars to weekly or monthly intervals when requested."""
    if interval == "1d":
        return df

    period_code = "W-FRI" if interval == "1wk" else "M"
    grouped = df.groupby(df["timestamp"].dt.to_period(period_code), sort=True)
    aggregated = grouped.agg(
        timestamp=("timestamp", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index(drop=True)
    return aggregated


class CSVMarketDataProvider:
    """Adapter loading OHLCV data from <csv_dir>/<TICKER>.csv files."""

    SOURCE_LABEL = "local_csv"
    FRESHNESS_NOTE = (
        "Static historical OHLCV dataset loaded from local CSV storage. "
        "Offline deterministic data source; not real-time market data."
    )

    def __init__(self, csv_dir: Path) -> None:
        self.csv_dir = Path(csv_dir).resolve()

    def list_available_tickers(self) -> list[str]:
        """Return sorted uppercase ticker symbols present in csv_dir."""
        if not self.csv_dir.exists() or not self.csv_dir.is_dir():
            return []
        return sorted(
            path.stem.upper()
            for path in self.csv_dir.glob("*.csv")
            if path.is_file()
        )

    def _resolve_csv_path(self, clean_ticker: str) -> Path:
        if not self.csv_dir.exists():
            raise SymbolNotFoundError(
                f"Local CSV directory does not exist for ticker '{clean_ticker}'.",
                details={"ticker": clean_ticker},
            )
        direct_path = (self.csv_dir / f"{clean_ticker}.csv").resolve()
        # Guard against directory escape.
        if direct_path.parent != self.csv_dir:
            raise InvalidRequestError(
                f"Invalid ticker symbol '{clean_ticker}'.",
                details={"ticker": clean_ticker},
            )
        if direct_path.is_file():
            return direct_path

        for candidate in self.csv_dir.glob("*.csv"):
            if candidate.stem.upper() == clean_ticker:
                return candidate

        raise SymbolNotFoundError(
            f"Ticker '{clean_ticker}' was not found in local CSV datasets.",
            details={
                "ticker": clean_ticker,
                "available_csv_tickers": self.list_available_tickers(),
            },
        )

    @staticmethod
    def _verify_csv_row_widths(csv_path: Path) -> None:
        """Detect jagged CSV rows (more or fewer values than headers) before pandas parsing."""
        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader, None)
                if header is None or all(not cell.strip() for cell in header):
                    raise EmptyDatasetError(
                        f"CSV file '{csv_path.name}' is empty.",
                        details={"file": csv_path.name},
                    )
                expected_cols = len(header)
                for line_num, row in enumerate(reader, start=2):
                    if not row or all(not cell.strip() for cell in row):
                        continue
                    if len(row) != expected_cols:
                        raise DataValidationError(
                            f"Malformed CSV row on line {line_num}: expected {expected_cols} columns, found {len(row)}.",
                            details={
                                "file": csv_path.name,
                                "line_number": line_num,
                                "expected_columns": expected_cols,
                                "actual_columns": len(row),
                            },
                        )
        except csv.Error as exc:
            raise DataValidationError(
                f"CSV syntax error in '{csv_path.name}': {exc}",
                details={"file": csv_path.name},
            ) from exc

    def fetch_ohlcv(
        self,
        ticker: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        interval: str = "1d",
    ) -> MarketDataResult:
        """Read, validate, normalize, and optionally resample local CSV OHLCV bars."""
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

        csv_path = self._resolve_csv_path(clean_ticker)
        self._verify_csv_row_widths(csv_path)

        try:
            raw_df = pd.read_csv(csv_path)
        except pd.errors.EmptyDataError as exc:
            raise EmptyDatasetError(
                f"CSV file '{csv_path.name}' contains no records.",
                details={"ticker": clean_ticker},
            ) from exc
        except pd.errors.ParserError as exc:
            raise DataValidationError(
                f"Failed to parse CSV file '{csv_path.name}': {exc}",
                details={"ticker": clean_ticker},
            ) from exc

        normalized = normalize_ohlcv_dataframe(
            raw_df,
            ticker=clean_ticker,
            start_date=start_date,
            end_date=end_date,
        )
        resampled = _resample_ohlcv(normalized, interval)
        if resampled.empty:
            raise EmptyDatasetError(
                f"No bars available for '{clean_ticker}' after '{interval}' aggregation.",
                details={"ticker": clean_ticker, "interval": interval},
            )

        return MarketDataResult(
            ticker=clean_ticker,
            interval=interval,
            source=self.SOURCE_LABEL,
            dataframe=resampled,
            freshness_note=self.FRESHNESS_NOTE,
            is_realtime=False,
        )
