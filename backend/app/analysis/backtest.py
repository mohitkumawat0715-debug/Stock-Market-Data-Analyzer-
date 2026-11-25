"""Look-ahead-safe long-only SMA crossover backtesting engine.

Next-Bar-Close Fill Convention (`execution_delay_bars = 1`):
    1. Signals (`BUY`, `SELL`) are calculated from `bar t`'s close (`desired_position[t]`).
    2. Orders fill at `bar t+1`'s close (`executed_position[t+1] = desired_position[t]`,
       with `reference_close = close[t+1]`).
    3. Because `bar_return[t+1]` measures the price move from `close[t]` to `close[t+1]`
       *before* the `bar t+1` close fill executes, `bar_return[t+1]` belongs to the
       position held prior to that fill (`earning_position[t+1] = executed_position[t]`).
       - Entry: A `BUY` at `bar t` close fills at `bar t+1` close and begins earning
         close-to-close returns starting on `bar t+2`.
       - Exit: A `SELL` at `bar u` close continues earning returns through `bar u+1`
         up to its `bar u+1` close fill, then earns zero starting on `bar u+2`.
    4. Proportional transaction costs (`transaction_cost_bps / 10_000`) are applied
       at each close fill event (`bar t+1` for entry, `bar u+1` for exit):
           strategy_net_return = (1 + strategy_gross_return) * (1 - transaction_cost) - 1

Interval Annualization Design:
    Annualized strategy volatility, per-bar risk-free rate conversion
    (`risk_free_rate_annual / periods_per_year`), and annualized Sharpe ratio
    use 252 periods/year for `1d`, 52 for `1wk`, and 12 for `1mo`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.analysis.indicators import (
    calculate_bar_returns,
    calculate_sma,
    get_periods_per_year,
)
from app.analysis.signals import append_sma_crossover_signals
from app.exceptions import InvalidRequestError
from app.providers.base import format_bar_timestamp


@dataclass(frozen=True)
class TradeRecord:
    """Single simulated order filled at the execution bar's close."""

    execution_timestamp: str
    signal_timestamp: str
    action: str
    reference_close: float
    cost_bps_applied: float


@dataclass(frozen=True)
class BacktestSummary:
    """Complete result bundle returned by `run_sma_crossover_backtest`."""

    interval: str
    periods_per_year: int
    sma_fast_window: int
    sma_slow_window: int
    initial_capital: float
    final_equity: float
    total_return: float
    total_return_pct: float
    benchmark_buy_and_hold_return: float
    annualized_volatility: float
    max_drawdown: float
    sharpe_ratio: float
    trade_count: int
    completed_round_trips: int
    transaction_cost_bps: float
    risk_free_rate_annual: float
    risk_free_rate_per_bar: float
    execution_delay_bars: int
    execution_fill_convention: str
    trades: list[TradeRecord]
    timeline: pd.DataFrame


def run_sma_crossover_backtest(
    ohlcv_df: pd.DataFrame,
    *,
    interval: str = "1d",
    sma_fast_window: int = 10,
    sma_slow_window: int = 30,
    initial_capital: float = 10_000.0,
    transaction_cost_bps: float = 10.0,
    risk_free_rate_annual: float = 0.02,
) -> BacktestSummary:
    """Simulate an educational long-only SMA crossover strategy with next-bar-close fills."""
    periods_per_year = get_periods_per_year(interval)

    if sma_fast_window < 2 or sma_slow_window < 3 or sma_fast_window >= sma_slow_window:
        raise InvalidRequestError(
            "Invalid SMA windows: require 2 <= sma_fast_window < sma_slow_window.",
            details={
                "sma_fast_window": sma_fast_window,
                "sma_slow_window": sma_slow_window,
            },
        )
    if initial_capital <= 0.0:
        raise InvalidRequestError(
            "initial_capital must be strictly positive.",
            details={"initial_capital": initial_capital},
        )
    if transaction_cost_bps < 0.0 or transaction_cost_bps > 1_000.0:
        raise InvalidRequestError(
            "transaction_cost_bps must be between 0 and 1000 basis points.",
            details={"transaction_cost_bps": transaction_cost_bps},
        )
    if risk_free_rate_annual < -0.10 or risk_free_rate_annual > 0.50:
        raise InvalidRequestError(
            "risk_free_rate_annual must be between -0.10 (-10%) and 0.50 (50%).",
            details={"risk_free_rate_annual": risk_free_rate_annual},
        )
    if len(ohlcv_df) < sma_slow_window + 2:
        raise InvalidRequestError(
            f"Dataset has {len(ohlcv_df)} bars, which is insufficient for sma_slow_window={sma_slow_window} "
            f"plus 1-bar delayed execution (minimum {sma_slow_window + 2} bars required).",
            details={
                "bar_count": int(len(ohlcv_df)),
                "minimum_required_bars": sma_slow_window + 2,
                "interval": interval,
            },
        )

    sim = ohlcv_df.copy().reset_index(drop=True)
    sim["bar_return"] = calculate_bar_returns(sim["close"])
    sim["sma_fast"] = calculate_sma(sim["close"], sma_fast_window)
    sim["sma_slow"] = calculate_sma(sim["close"], sma_slow_window)
    sim = append_sma_crossover_signals(sim)

    # Target position decided at bar t close: 1.0 after BUY crossover, 0.0 after SELL crossover.
    desired_positions: list[float] = []
    current_desired = 0.0
    for sig in sim["signal"].tolist():
        if sig == "BUY":
            current_desired = 1.0
        elif sig == "SELL":
            current_desired = 0.0
        desired_positions.append(current_desired)

    sim["desired_position"] = pd.Series(desired_positions, index=sim.index, dtype="float64")

    # Next-bar-close fill (execution_delay_bars = 1):
    # `executed_position[k]` is the position held AFTER bar k's close fill.
    sim["executed_position"] = sim["desired_position"].shift(1).fillna(0.0)

    # `earning_position[k]` is the position held BEFORE bar k's close fill (i.e., after
    # bar k-1's close), which earns the close[k-1] -> close[k] return (`bar_return[k]`).
    sim["earning_position"] = sim["executed_position"].shift(1).fillna(0.0)

    # Fill events occur at bar k close whenever `executed_position[k]` differs from
    # the position held going into bar k (`earning_position[k]`).
    turnover = (sim["executed_position"] - sim["earning_position"]).abs()
    cost_rate = transaction_cost_bps / 10_000.0
    sim["transaction_cost"] = turnover * cost_rate

    asset_returns = sim["bar_return"].fillna(0.0)
    sim["strategy_gross_return"] = sim["earning_position"] * asset_returns
    sim["strategy_net_return"] = (
        (1.0 + sim["strategy_gross_return"]) * (1.0 - sim["transaction_cost"]) - 1.0
    )

    sim["equity"] = float(initial_capital) * (1.0 + sim["strategy_net_return"]).cumprod()
    running_peak = sim["equity"].cummax()
    sim["drawdown"] = (sim["equity"] - running_peak) / running_peak

    # Collect executed trade records at each bar close fill.
    trades: list[TradeRecord] = []
    for idx in range(1, len(sim)):
        delta_pos = float(sim["executed_position"].iloc[idx] - sim["earning_position"].iloc[idx])
        if delta_pos > 0.0:
            trades.append(
                TradeRecord(
                    execution_timestamp=format_bar_timestamp(pd.Timestamp(sim["timestamp"].iloc[idx])),
                    signal_timestamp=format_bar_timestamp(pd.Timestamp(sim["timestamp"].iloc[idx - 1])),
                    action="BUY_ENTRY",
                    reference_close=float(sim["close"].iloc[idx]),
                    cost_bps_applied=float(transaction_cost_bps),
                )
            )
        elif delta_pos < 0.0:
            trades.append(
                TradeRecord(
                    execution_timestamp=format_bar_timestamp(pd.Timestamp(sim["timestamp"].iloc[idx])),
                    signal_timestamp=format_bar_timestamp(pd.Timestamp(sim["timestamp"].iloc[idx - 1])),
                    action="SELL_EXIT",
                    reference_close=float(sim["close"].iloc[idx]),
                    cost_bps_applied=float(transaction_cost_bps),
                )
            )

    final_equity = float(sim["equity"].iloc[-1])
    total_return = (final_equity / float(initial_capital)) - 1.0
    benchmark_return = float(sim["close"].iloc[-1] / sim["close"].iloc[0]) - 1.0

    net_returns = sim["strategy_net_return"]
    ret_std = float(net_returns.std(ddof=1)) if len(net_returns) > 1 else 0.0
    annualized_vol = ret_std * float(np.sqrt(periods_per_year)) if ret_std > 0.0 else 0.0
    max_drawdown = float(sim["drawdown"].min())

    # Convert annual risk-free rate into a per-bar rate using periods_per_year
    # (252 for 1d, 52 for 1wk, 12 for 1mo) and scale Sharpe by sqrt(periods_per_year).
    per_bar_rf = float(risk_free_rate_annual) / float(periods_per_year)
    if ret_std > 1e-12:
        excess_bar_returns = net_returns - per_bar_rf
        sharpe_ratio = float(
            (excess_bar_returns.mean() / excess_bar_returns.std(ddof=1))
            * np.sqrt(periods_per_year)
        )
    else:
        sharpe_ratio = 0.0

    completed_round_trips = sum(1 for trade in trades if trade.action == "SELL_EXIT")

    return BacktestSummary(
        interval=interval,
        periods_per_year=periods_per_year,
        sma_fast_window=sma_fast_window,
        sma_slow_window=sma_slow_window,
        initial_capital=float(initial_capital),
        final_equity=final_equity,
        total_return=total_return,
        total_return_pct=total_return * 100.0,
        benchmark_buy_and_hold_return=benchmark_return,
        annualized_volatility=annualized_vol,
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
        trade_count=len(trades),
        completed_round_trips=completed_round_trips,
        transaction_cost_bps=float(transaction_cost_bps),
        risk_free_rate_annual=float(risk_free_rate_annual),
        risk_free_rate_per_bar=per_bar_rf,
        execution_delay_bars=1,
        execution_fill_convention="next_bar_close",
        trades=trades,
        timeline=sim,
    )
