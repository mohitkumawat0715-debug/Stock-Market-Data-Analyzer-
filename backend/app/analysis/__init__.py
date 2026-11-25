"""Pure domain layer for technical indicators, educational signals, and backtesting."""

from app.analysis.backtest import BacktestSummary, run_sma_crossover_backtest
from app.analysis.indicators import (
    PERIODS_PER_YEAR_BY_INTERVAL,
    WARMUP_POLICY_DESCRIPTION,
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

__all__ = [
    "BacktestSummary",
    "PERIODS_PER_YEAR_BY_INTERVAL",
    "WARMUP_POLICY_DESCRIPTION",
    "append_sma_crossover_signals",
    "calculate_bar_returns",
    "calculate_ema",
    "calculate_macd",
    "calculate_rolling_volatility",
    "calculate_rsi",
    "calculate_sma",
    "compute_indicator_dataframe",
    "get_periods_per_year",
    "run_sma_crossover_backtest",
    "summarize_signals",
]
