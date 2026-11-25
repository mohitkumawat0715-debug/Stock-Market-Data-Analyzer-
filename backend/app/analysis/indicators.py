"""Pure vectorized technical indicator calculations on canonical OHLCV data.

Warm-up and Missing-Value Policy:
    Every indicator requires its full lookback window before emitting numeric
    values (`min_periods` equals the window length). Rows inside the initial
    warm-up window remain `NaN` in pandas and serialize to `null` in JSON API
    responses rather than backfilling or fabricating partial-window estimates.

Interval Annualization Policy:
    Annualized volatility scales the sample per-bar return standard deviation
    by `sqrt(periods_per_year)` using 252 for `1d`, 52 for `1wk`, and 12 for `1mo`.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

from app.exceptions import InvalidRequestError

WARMUP_POLICY_DESCRIPTION = (
    "Indicators require a full lookback window (min_periods = window). "
    "Initial warm-up rows remain null rather than backfilling or using partial windows."
)

PERIODS_PER_YEAR_BY_INTERVAL: Final[dict[str, int]] = {
    "1d": 252,
    "1wk": 52,
    "1mo": 12,
}


def get_periods_per_year(interval: str) -> int:
    """Return the annualization factor (periods per year) for a supported bar interval."""
    if interval not in PERIODS_PER_YEAR_BY_INTERVAL:
        raise InvalidRequestError(
            f"Unsupported interval '{interval}'. Supported intervals: 1d, 1wk, 1mo.",
            details={
                "interval": interval,
                "supported_intervals": list(PERIODS_PER_YEAR_BY_INTERVAL.keys()),
            },
        )
    return PERIODS_PER_YEAR_BY_INTERVAL[interval]


def _require_positive_window(name: str, value: int, minimum: int = 2) -> None:
    if value < minimum:
        raise InvalidRequestError(
            f"Parameter '{name}' must be at least {minimum} (received {value}).",
            details={"parameter": name, "value": value, "minimum": minimum},
        )


def calculate_bar_returns(close: pd.Series) -> pd.Series:
    """Compute close-to-close simple per-bar return: (close_t / close_{t-1}) - 1.

    Row 0 is NaN because there is no prior bar in the series.
    """
    return close.astype("float64").pct_change()


def calculate_sma(close: pd.Series, window: int) -> pd.Series:
    """Compute Simple Moving Average with strict warm-up (first window - 1 rows NaN)."""
    _require_positive_window("sma_window", window, minimum=2)
    return close.astype("float64").rolling(window=window, min_periods=window).mean()


def calculate_ema(close: pd.Series, window: int) -> pd.Series:
    """Compute standard Exponential Moving Average (span=window, min_periods=window)."""
    _require_positive_window("ema_window", window, minimum=2)
    return (
        close.astype("float64")
        .ewm(span=window, adjust=False, min_periods=window)
        .mean()
    )


def calculate_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Compute Wilder's Relative Strength Index bounded in [0, 100].

    Because price differences start on index 1, the first `window` rows
    (indices 0 .. window - 1) are NaN during warm-up.
    """
    _require_positive_window("rsi_window", window, minimum=2)
    prices = close.astype("float64")
    delta = prices.diff()

    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)

    # Wilder smoothing uses alpha = 1 / window on valid price changes (starting at index 1).
    avg_gain = gains.iloc[1:].ewm(
        alpha=1.0 / window, adjust=False, min_periods=window
    ).mean()
    avg_loss = losses.iloc[1:].ewm(
        alpha=1.0 / window, adjust=False, min_periods=window
    ).mean()

    rsi_tail = pd.Series(np.nan, index=prices.index[1:], dtype="float64")
    valid_mask = avg_gain.notna() & avg_loss.notna()

    for idx in rsi_tail.index[valid_mask]:
        gain_val = float(avg_gain.loc[idx])
        loss_val = float(avg_loss.loc[idx])
        if loss_val == 0.0 and gain_val == 0.0:
            rsi_tail.loc[idx] = 50.0
        elif loss_val == 0.0:
            rsi_tail.loc[idx] = 100.0
        else:
            rs = gain_val / loss_val
            rsi_tail.loc[idx] = 100.0 - (100.0 / (1.0 + rs))

    result = pd.Series(np.nan, index=prices.index, dtype="float64")
    result.iloc[1:] = rsi_tail
    return result


def calculate_macd(
    close: pd.Series,
    fast_window: int = 12,
    slow_window: int = 26,
    signal_window: int = 9,
) -> pd.DataFrame:
    """Compute MACD line, signal line, and histogram.

    Warm-up behavior:
        - macd_line becomes non-null starting at index (slow_window - 1).
        - macd_signal and macd_histogram become non-null after `signal_window`
          valid macd_line observations, i.e., index (slow_window + signal_window - 2).
    """
    _require_positive_window("macd_fast_window", fast_window, minimum=2)
    _require_positive_window("macd_slow_window", slow_window, minimum=3)
    _require_positive_window("macd_signal_window", signal_window, minimum=2)
    if fast_window >= slow_window:
        raise InvalidRequestError(
            "macd_fast_window must be strictly smaller than macd_slow_window.",
            details={
                "macd_fast_window": fast_window,
                "macd_slow_window": slow_window,
            },
        )

    ema_fast = calculate_ema(close, fast_window)
    ema_slow = calculate_ema(close, slow_window)
    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(
        span=signal_window, adjust=False, min_periods=signal_window
    ).mean()
    macd_histogram = macd_line - macd_signal

    return pd.DataFrame(
        {
            "macd_line": macd_line,
            "macd_signal": macd_signal,
            "macd_histogram": macd_histogram,
        },
        index=close.index,
    )


def calculate_rolling_volatility(
    bar_returns: pd.Series,
    window: int = 20,
    *,
    interval: str = "1d",
) -> pd.Series:
    """Compute annualized sample rolling standard deviation of per-bar returns."""
    _require_positive_window("volatility_window", window, minimum=2)
    periods_per_year = get_periods_per_year(interval)
    rolling_std = bar_returns.rolling(window=window, min_periods=window).std(ddof=1)
    return rolling_std * float(np.sqrt(periods_per_year))


def compute_indicator_dataframe(
    ohlcv_df: pd.DataFrame,
    *,
    interval: str = "1d",
    sma_fast_window: int = 10,
    sma_slow_window: int = 30,
    ema_window: int = 20,
    rsi_window: int = 14,
    macd_fast_window: int = 12,
    macd_slow_window: int = 26,
    macd_signal_window: int = 9,
    volatility_window: int = 20,
) -> pd.DataFrame:
    """Return a copy of canonical OHLCV DataFrame enriched with all technical indicators."""
    get_periods_per_year(interval)
    if sma_fast_window >= sma_slow_window:
        raise InvalidRequestError(
            "sma_fast_window must be strictly smaller than sma_slow_window.",
            details={
                "sma_fast_window": sma_fast_window,
                "sma_slow_window": sma_slow_window,
            },
        )

    out = ohlcv_df.copy()
    close = out["close"]

    out["bar_return"] = calculate_bar_returns(close)
    out["sma_fast"] = calculate_sma(close, sma_fast_window)
    out["sma_slow"] = calculate_sma(close, sma_slow_window)
    out["ema"] = calculate_ema(close, ema_window)
    out["rsi"] = calculate_rsi(close, rsi_window)

    macd_df = calculate_macd(
        close,
        fast_window=macd_fast_window,
        slow_window=macd_slow_window,
        signal_window=macd_signal_window,
    )
    out["macd_line"] = macd_df["macd_line"]
    out["macd_signal"] = macd_df["macd_signal"]
    out["macd_histogram"] = macd_df["macd_histogram"]
    out["rolling_volatility"] = calculate_rolling_volatility(
        out["bar_return"], window=volatility_window, interval=interval
    )
    return out
