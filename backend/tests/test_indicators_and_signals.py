"""Unit tests for technical indicators, interval annualization, warm-ups, and signals."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis.indicators import (
    calculate_bar_returns,
    calculate_ema,
    calculate_macd,
    calculate_rolling_volatility,
    calculate_rsi,
    calculate_sma,
    compute_indicator_dataframe,
    get_periods_per_year,
)
from app.analysis.signals import append_sma_crossover_signals, summarize_signals
from app.exceptions import InvalidRequestError


def test_bar_returns_and_sma_warmup_exact() -> None:
    close = pd.Series([100.0, 110.0, 121.0, 115.0, 125.0])
    returns = calculate_bar_returns(close)
    assert pd.isna(returns.iloc[0])
    assert returns.iloc[1] == pytest.approx(0.10)
    assert returns.iloc[2] == pytest.approx(0.10)

    sma3 = calculate_sma(close, window=3)
    assert sma3.iloc[:2].isna().all()
    assert sma3.iloc[2] == pytest.approx((100.0 + 110.0 + 121.0) / 3.0)
    assert sma3.iloc[4] == pytest.approx((121.0 + 115.0 + 125.0) / 3.0)


def test_ema_and_macd_warmup_and_identities(deterministic_ohlcv_df: pd.DataFrame) -> None:
    close = deterministic_ohlcv_df["close"]
    ema10 = calculate_ema(close, window=10)
    assert ema10.iloc[:9].isna().all()
    assert ema10.iloc[9:].notna().all()

    macd = calculate_macd(close, fast_window=12, slow_window=26, signal_window=9)
    # macd_line warms up at index 25 (slow_window - 1); signal warms up 8 bars later at index 33.
    assert macd["macd_line"].iloc[:25].isna().all()
    assert macd["macd_line"].iloc[25:].notna().all()
    assert macd["macd_signal"].iloc[:33].isna().all()
    assert macd["macd_signal"].iloc[33:].notna().all()

    valid = macd.iloc[33:]
    np.testing.assert_allclose(
        valid["macd_histogram"].to_numpy(),
        (valid["macd_line"] - valid["macd_signal"]).to_numpy(),
        rtol=1e-9,
        atol=1e-9,
    )


def test_rsi_bounds_monotonic_and_flat_series() -> None:
    rising = pd.Series([100.0 + i for i in range(25)])
    rsi_up = calculate_rsi(rising, window=14)
    assert rsi_up.iloc[:14].isna().all()
    assert rsi_up.iloc[14] == pytest.approx(100.0)

    flat = pd.Series([50.0] * 25)
    rsi_flat = calculate_rsi(flat, window=14)
    assert rsi_flat.iloc[14] == pytest.approx(50.0)


@pytest.mark.parametrize(
    ("interval", "expected_periods"),
    [("1d", 252), ("1wk", 52), ("1mo", 12)],
)
def test_rolling_volatility_and_indicator_frame_respect_interval(
    deterministic_ohlcv_df: pd.DataFrame,
    interval: str,
    expected_periods: int,
) -> None:
    assert get_periods_per_year(interval) == expected_periods

    returns = pd.Series([np.nan, 0.01, -0.01, 0.02, -0.02, 0.01])
    vol = calculate_rolling_volatility(returns, window=4, interval=interval)
    assert vol.iloc[:4].isna().all()
    expected = returns.iloc[1:5].std(ddof=1) * np.sqrt(expected_periods)
    assert vol.iloc[4] == pytest.approx(expected)

    ind_df = compute_indicator_dataframe(
        deterministic_ohlcv_df,
        interval=interval,
        sma_fast_window=5,
        sma_slow_window=15,
        volatility_window=10,
    )
    assert "bar_return" in ind_df.columns
    assert "daily_return" not in ind_df.columns
    expected_last_vol = (
        ind_df["bar_return"].iloc[-10:].std(ddof=1) * np.sqrt(expected_periods)
    )
    assert ind_df["rolling_volatility"].iloc[-1] == pytest.approx(expected_last_vol)


def test_unsupported_interval_rejected_in_indicators(
    deterministic_ohlcv_df: pd.DataFrame,
) -> None:
    with pytest.raises(InvalidRequestError, match="Unsupported interval"):
        get_periods_per_year("4h")

    with pytest.raises(InvalidRequestError, match="Unsupported interval"):
        compute_indicator_dataframe(deterministic_ohlcv_df, interval="1h")


def test_sma_crossover_signals_and_invalid_windows(
    deterministic_ohlcv_df: pd.DataFrame,
) -> None:
    with pytest.raises(InvalidRequestError):
        compute_indicator_dataframe(
            deterministic_ohlcv_df, sma_fast_window=30, sma_slow_window=10
        )

    ind_df = compute_indicator_dataframe(
        deterministic_ohlcv_df, sma_fast_window=5, sma_slow_window=15
    )
    sig_df = append_sma_crossover_signals(ind_df)
    summary = summarize_signals(sig_df)

    # First 14 rows (indices 0..13) must be WARMUP because sma_slow=15 requires 15 bars.
    assert summary["WARMUP"] == 14
    assert summary["BUY"] >= 1
    assert summary["SELL"] >= 1
    assert summary["NEUTRAL"] >= 1
    assert sum(summary.values()) == len(deterministic_ohlcv_df)
