"""Educational Moving-Average Crossover signal generation.

Notice:
    Signals generated here illustrate mechanical moving-average relationships
    for coursework and software architecture demonstration. They are not
    investment recommendations or price forecasts.
"""

from __future__ import annotations

import pandas as pd


def append_sma_crossover_signals(indicator_df: pd.DataFrame) -> pd.DataFrame:
    """Append discrete `signal` and continuous `regime` columns from `sma_fast` and `sma_slow`.

    States:
        - `WARMUP`: Either `sma_fast` or `sma_slow` is NaN (insufficient history).
        - `BUY`: `sma_fast > sma_slow` on bar t AND on bar t-1 both SMAs were valid with `sma_fast <= sma_slow`.
        - `SELL`: `sma_fast < sma_slow` on bar t AND on bar t-1 both SMAs were valid with `sma_fast >= sma_slow`.
        - `NEUTRAL`: Post-warmup bar where no fresh crossover occurred.
    """
    out = indicator_df.copy()
    fast = out["sma_fast"]
    slow = out["sma_slow"]

    signals: list[str] = []
    regimes: list[str] = []

    prev_valid = False
    prev_diff = 0.0

    for idx in range(len(out)):
        f_val = fast.iloc[idx]
        s_val = slow.iloc[idx]

        if pd.isna(f_val) or pd.isna(s_val):
            signals.append("WARMUP")
            regimes.append("WARMUP")
            prev_valid = False
            continue

        diff = float(f_val) - float(s_val)
        if diff > 0.0:
            regime = "BULLISH"
        elif diff < 0.0:
            regime = "BEARISH"
        else:
            regime = "NEUTRAL"

        if prev_valid and diff > 0.0 and prev_diff <= 0.0:
            signal = "BUY"
        elif prev_valid and diff < 0.0 and prev_diff >= 0.0:
            signal = "SELL"
        else:
            signal = "NEUTRAL"

        signals.append(signal)
        regimes.append(regime)
        prev_valid = True
        prev_diff = diff

    out["signal"] = signals
    out["regime"] = regimes
    return out


def summarize_signals(df_with_signals: pd.DataFrame) -> dict[str, int]:
    """Count occurrences of each discrete signal state across the series."""
    counts = df_with_signals["signal"].value_counts().to_dict()
    return {
        "WARMUP": int(counts.get("WARMUP", 0)),
        "BUY": int(counts.get("BUY", 0)),
        "SELL": int(counts.get("SELL", 0)),
        "NEUTRAL": int(counts.get("NEUTRAL", 0)),
    }
