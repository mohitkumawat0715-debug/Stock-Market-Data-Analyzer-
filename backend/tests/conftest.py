"""Shared deterministic offline fixtures for backend unit and API tests."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.providers.normalizer import normalize_ohlcv_dataframe


@pytest.fixture()
def deterministic_ohlcv_df() -> pd.DataFrame:
    """Return an 80-bar canonical OHLCV DataFrame with a clear cyclical price wave."""
    dates = pd.bdate_range("2025-01-02", periods=80)
    rows: list[dict[str, object]] = []
    for idx, dt in enumerate(dates):
        # Smooth deterministic wave that crosses its moving averages cleanly
        close = round(100.0 + 12.0 * math.sin(idx / 6.0) + 0.25 * idx, 2)
        open_p = round(close - 0.40, 2)
        high = round(max(open_p, close) + 1.10, 2)
        low = round(min(open_p, close) - 1.10, 2)
        volume = float(1_000_000 + idx * 5_000)
        rows.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "open": open_p,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
    raw = pd.DataFrame(rows)
    return normalize_ohlcv_dataframe(raw, ticker="DEMO")


@pytest.fixture()
def temp_csv_dir(tmp_path: Path, deterministic_ohlcv_df: pd.DataFrame) -> Path:
    """Create a temporary CSV directory containing valid DEMO.csv and broken fixtures."""
    csv_dir = tmp_path / "csv_data"
    csv_dir.mkdir(parents=True, exist_ok=True)

    demo_out = deterministic_ohlcv_df.copy()
    demo_out["timestamp"] = demo_out["timestamp"].dt.strftime("%Y-%m-%d")
    demo_out.rename(columns={"timestamp": "date"}).to_csv(
        csv_dir / "DEMO.csv", index=False
    )

    # Create an intentionally invalid OHLC file (high < low) for error-path testing.
    bad_df = pd.DataFrame(
        [
            {
                "date": "2025-01-02",
                "open": 100.0,
                "high": 95.0,
                "low": 98.0,
                "close": 97.0,
                "volume": 5000,
            }
        ]
    )
    bad_df.to_csv(csv_dir / "BADOHLC.csv", index=False)

    return csv_dir
