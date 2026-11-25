"""Canonical OHLCV schema normalization and defensive data validation."""

from __future__ import annotations

from datetime import date, datetime
from typing import Final

import numpy as np
import pandas as pd

from app.exceptions import DataValidationError, EmptyDatasetError, InvalidRequestError

CANONICAL_COLUMNS: Final[tuple[str, ...]] = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
)
PRICE_COLUMNS: Final[tuple[str, ...]] = ("open", "high", "low", "close")
NUMERIC_COLUMNS: Final[tuple[str, ...]] = ("open", "high", "low", "close", "volume")
TIMESTAMP_ALIASES: Final[tuple[str, ...]] = ("date", "datetime", "time")
FLOAT_TOLERANCE: Final[float] = 1e-6


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns (returned by some yfinance calls) cleanly."""
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        flattened = [str(col[0]).strip() for col in out.columns]
        out.columns = flattened
    return out


def _parse_timestamp_series(raw_series: pd.Series) -> pd.Series:
    """Parse timestamps into timezone-naive pd.Timestamp values without shifting trading dates."""
    if raw_series.isna().any():
        bad_indices = raw_series[raw_series.isna()].index.tolist()[:5]
        raise DataValidationError(
            "Dataset contains missing or null timestamp values.",
            details={"invalid_row_indices": bad_indices},
        )

    # Check blank string cells explicitly before pandas coercion.
    if raw_series.dtype == object or pd.api.types.is_string_dtype(raw_series):
        str_vals = raw_series.astype(str).str.strip()
        blank_mask = str_vals.eq("") | str_vals.str.lower().isin({"nan", "none", "nat"})
        if blank_mask.any():
            bad_indices = raw_series[blank_mask].index.tolist()[:5]
            raise DataValidationError(
                "Dataset contains blank timestamp values.",
                details={"invalid_row_indices": bad_indices},
            )

    # If already a timezone-aware DatetimeSeries, strip tz while keeping exchange calendar date.
    if isinstance(raw_series.dtype, pd.DatetimeTZDtype):
        return raw_series.dt.tz_localize(None)

    if pd.api.types.is_datetime64_any_dtype(raw_series):
        return pd.to_datetime(raw_series)

    # Parse element-wise when strings may include mixed ISO offsets so each bar keeps
    # its stated trading calendar date/time cleanly.
    parsed_values: list[pd.Timestamp] = []
    bad_samples: list[str] = []
    for raw_val in raw_series.tolist():
        try:
            ts = pd.Timestamp(raw_val)
            if pd.isna(ts):
                bad_samples.append(str(raw_val))
                continue
            if ts.tzinfo is not None:
                ts = ts.tz_localize(None)
            parsed_values.append(ts)
        except Exception:
            bad_samples.append(str(raw_val))

    if bad_samples:
        raise DataValidationError(
            "Dataset contains unparseable timestamp or date values.",
            details={"invalid_timestamps": bad_samples[:5]},
        )

    return pd.Series(parsed_values, index=raw_series.index, dtype="datetime64[ns]")


def normalize_ohlcv_dataframe(
    raw_df: pd.DataFrame,
    *,
    ticker: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """Validate and normalize raw market data into canonical OHLCV format.

    Canonical output columns:
        timestamp (datetime64[ns]), open, high, low, close, volume (float64)
    """
    if start_date is not None and end_date is not None and start_date > end_date:
        raise InvalidRequestError(
            "start_date must be earlier than or equal to end_date.",
            details={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )

    if raw_df is None or raw_df.empty:
        raise EmptyDatasetError(
            f"No market data rows were returned for ticker '{ticker}'.",
            details={"ticker": ticker},
        )

    df = _flatten_columns(raw_df)

    # Promote DatetimeIndex (or named index) to a regular column if needed.
    normalized_existing = {str(c).strip().lower() for c in df.columns}
    has_ts_col = "timestamp" in normalized_existing or any(
        alias in normalized_existing for alias in TIMESTAMP_ALIASES
    )
    if not has_ts_col and (
        isinstance(df.index, pd.DatetimeIndex)
        or (
            df.index.name is not None
            and str(df.index.name).strip().lower()
            in ("timestamp", *TIMESTAMP_ALIASES)
        )
    ):
        df = df.reset_index()
        if df.columns[0] == "index":
            df = df.rename(columns={"index": "timestamp"})

    # Reject unnamed overflow columns produced by malformed CSV rows.
    unnamed_cols = [
        str(c) for c in df.columns if str(c).strip().lower().startswith("unnamed:")
    ]
    if unnamed_cols:
        raise DataValidationError(
            "Dataset contains unnamed or extra malformed columns.",
            details={"unnamed_columns": unnamed_cols},
        )

    cleaned_names = [str(c).strip().lower() for c in df.columns]
    if len(cleaned_names) != len(set(cleaned_names)):
        raise DataValidationError(
            "Dataset contains duplicate column headers after case normalization.",
            details={"columns": cleaned_names},
        )
    df.columns = cleaned_names

    # Map date/datetime alias to canonical 'timestamp'.
    present_ts_candidates = [
        col for col in ("timestamp", *TIMESTAMP_ALIASES) if col in df.columns
    ]
    if len(present_ts_candidates) > 1:
        raise DataValidationError(
            "Dataset contains multiple ambiguous date/timestamp columns.",
            details={"timestamp_columns": present_ts_candidates},
        )
    if len(present_ts_candidates) == 1 and present_ts_candidates[0] != "timestamp":
        df = df.rename(columns={present_ts_candidates[0]: "timestamp"})

    missing_columns = [col for col in CANONICAL_COLUMNS if col not in df.columns]
    if missing_columns:
        raise DataValidationError(
            f"Dataset is missing required OHLCV columns: {', '.join(missing_columns)}.",
            details={"missing_columns": missing_columns, "found_columns": list(df.columns)},
        )

    df = df.loc[:, list(CANONICAL_COLUMNS)].copy()
    df["timestamp"] = _parse_timestamp_series(df["timestamp"])

    # Detect duplicate timestamps before sorting or filtering.
    duplicate_mask = df["timestamp"].duplicated(keep=False)
    if duplicate_mask.any():
        dup_values = (
            df.loc[duplicate_mask, "timestamp"]
            .dt.strftime("%Y-%m-%dT%H:%M:%S")
            .unique()
            .tolist()[:5]
        )
        raise DataValidationError(
            "Dataset contains duplicate timestamps.",
            details={"duplicate_timestamps": dup_values},
        )

    # Validate numeric OHLCV columns.
    for col in NUMERIC_COLUMNS:
        series = df[col]
        if series.isna().any():
            bad_rows = series[series.isna()].index.tolist()[:5]
            raise DataValidationError(
                f"Column '{col}' contains missing or null values.",
                details={"column": col, "invalid_row_indices": bad_rows},
            )
        coerced = pd.to_numeric(series, errors="coerce")
        invalid_numeric = coerced.isna() | ~np.isfinite(coerced)
        if invalid_numeric.any():
            bad_rows = series[invalid_numeric].index.tolist()[:5]
            raise DataValidationError(
                f"Column '{col}' contains non-numeric or non-finite values.",
                details={"column": col, "invalid_row_indices": bad_rows},
            )
        df[col] = coerced.astype("float64")

    # Enforce positive prices and non-negative volume.
    for col in PRICE_COLUMNS:
        non_positive = df[col] <= 0.0
        if non_positive.any():
            bad_dates = (
                df.loc[non_positive, "timestamp"].dt.strftime("%Y-%m-%d").tolist()[:5]
            )
            raise DataValidationError(
                f"Price column '{col}' must contain strictly positive numbers.",
                details={"column": col, "invalid_timestamps": bad_dates},
            )

    neg_volume = df["volume"] < 0.0
    if neg_volume.any():
        bad_dates = df.loc[neg_volume, "timestamp"].dt.strftime("%Y-%m-%d").tolist()[:5]
        raise DataValidationError(
            "Volume column cannot contain negative values.",
            details={"column": "volume", "invalid_timestamps": bad_dates},
        )

    # Enforce structural OHLC invariants: low <= open, close <= high and low <= high.
    high_lt_low = (df["high"] + FLOAT_TOLERANCE) < df["low"]
    high_lt_body = ((df["high"] + FLOAT_TOLERANCE) < df["open"]) | (
        (df["high"] + FLOAT_TOLERANCE) < df["close"]
    )
    low_gt_body = ((df["low"] - FLOAT_TOLERANCE) > df["open"]) | (
        (df["low"] - FLOAT_TOLERANCE) > df["close"]
    )
    invalid_ohlc = high_lt_low | high_lt_body | low_gt_body
    if invalid_ohlc.any():
        bad_dates = (
            df.loc[invalid_ohlc, "timestamp"].dt.strftime("%Y-%m-%d").tolist()[:5]
        )
        raise DataValidationError(
            "Dataset contains bars with invalid OHLC relationships "
            "(expected low <= open <= high and low <= close <= high).",
            details={"invalid_timestamps": bad_dates},
        )

    df = df.sort_values("timestamp", ascending=True).reset_index(drop=True)

    # Apply inclusive date-window filtering when specified.
    if start_date is not None:
        start_ts = pd.Timestamp(datetime.combine(start_date, datetime.min.time()))
        df = df.loc[df["timestamp"] >= start_ts]
    if end_date is not None:
        end_ts = pd.Timestamp(
            datetime.combine(end_date, datetime.max.time()).replace(microsecond=999999)
        )
        df = df.loc[df["timestamp"] <= end_ts]

    df = df.reset_index(drop=True)
    if df.empty:
        raise EmptyDatasetError(
            f"No OHLCV bars found for ticker '{ticker}' within the requested date range.",
            details={
                "ticker": ticker,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
            },
        )

    return df
