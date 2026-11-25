"""Unit tests verifying next-bar-close fill timing, fee placement, and interval scaling."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis.backtest import run_sma_crossover_backtest
from app.exceptions import InvalidRequestError
from app.providers.normalizer import normalize_ohlcv_dataframe


def _make_ohlcv_from_closes(closes: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=len(closes))
    raw = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": closes,
            "high": [c + 1.0 for c in closes],
            "low": [max(0.5, c - 1.0) for c in closes],
            "close": closes,
            "volume": [100_000.0] * len(closes),
        }
    )
    return normalize_ohlcv_dataframe(raw, ticker="SYNTH")


def test_backtest_strictly_prevents_lookahead_bias() -> None:
    """Prove a +50% spike that triggers a BUY crossover on bar t is NOT captured on bar t.

    Price path:
        - Bars 0..5: close = 100.0 (SMA(2) == SMA(4) == 100.0, desired_position = 0)
        - Bar 6: close jumps +50% to 150.0 -> SMA(2)=125 > SMA(4)=112.5 -> BUY signal at bar 6 close
        - Bars 7..11: close stays flat at 150.0 (trade fills at bar 7 close, 0% return thereafter)
    """
    closes = [100.0] * 6 + [150.0] * 6
    df = _make_ohlcv_from_closes(closes)

    summary = run_sma_crossover_backtest(
        df,
        interval="1d",
        sma_fast_window=2,
        sma_slow_window=4,
        initial_capital=10_000.0,
        transaction_cost_bps=0.0,
        risk_free_rate_annual=0.0,
    )

    assert summary.execution_delay_bars == 1
    assert summary.execution_fill_convention == "next_bar_close"
    assert summary.trade_count >= 1
    first_trade = summary.trades[0]
    assert first_trade.action == "BUY_ENTRY"
    assert first_trade.signal_timestamp == df["timestamp"].iloc[6].strftime("%Y-%m-%d")
    assert first_trade.execution_timestamp == df["timestamp"].iloc[7].strftime("%Y-%m-%d")
    assert summary.total_return == pytest.approx(0.0, abs=1e-9)
    assert summary.final_equity == pytest.approx(10_000.0, abs=1e-6)


def test_next_bar_close_fill_entry_skips_fill_bar_gap_and_earns_subsequent_return() -> None:
    """Regression test for next-bar-close entry timing:
    1. Bar 6 close (110.0) triggers a BUY signal (SMA(2)=105 > SMA(4)=102.5).
    2. Bar 7 surges +100% from 110.0 to 220.0, and BUY_ENTRY fills at Bar 7's close (220.0).
    3. New position MUST NOT earn Bar 7's pre-fill 110 -> 220 movement.
    4. Bar 8 rises +10% from 220.0 to 242.0; new position MUST earn that +10% post-fill return.
    """
    closes = [100.0] * 6 + [110.0, 220.0, 242.0, 242.0]
    df = _make_ohlcv_from_closes(closes)

    summary = run_sma_crossover_backtest(
        df,
        interval="1d",
        sma_fast_window=2,
        sma_slow_window=4,
        initial_capital=10_000.0,
        transaction_cost_bps=0.0,
        risk_free_rate_annual=0.0,
    )

    tl = summary.timeline
    assert tl["signal"].iloc[6] == "BUY"
    assert summary.trades[0].signal_timestamp == df["timestamp"].iloc[6].strftime("%Y-%m-%d")
    assert summary.trades[0].execution_timestamp == df["timestamp"].iloc[7].strftime("%Y-%m-%d")
    assert summary.trades[0].reference_close == pytest.approx(220.0)

    # Bar 7 (the fill bar): executed_position becomes 1.0 at close, but earning_position was 0.0.
    assert tl["executed_position"].iloc[7] == pytest.approx(1.0)
    assert tl["earning_position"].iloc[7] == pytest.approx(0.0)
    assert tl["strategy_gross_return"].iloc[7] == pytest.approx(0.0, abs=1e-12)
    assert tl["equity"].iloc[7] == pytest.approx(10_000.0, abs=1e-9)

    # Bar 8 (first post-fill bar): earns +10% (242 / 220 - 1).
    assert tl["earning_position"].iloc[8] == pytest.approx(1.0)
    assert tl["strategy_gross_return"].iloc[8] == pytest.approx(0.10, abs=1e-9)
    assert tl["equity"].iloc[8] == pytest.approx(11_000.0, abs=1e-6)
    assert summary.total_return == pytest.approx(0.10, abs=1e-9)


def test_next_bar_close_fill_exit_timing_and_transaction_cost_placement() -> None:
    """Regression test covering exit fill-bar return capture, post-exit flat state, and fee placement.

    Path (SMA fast=2, slow=4, fee=100 bps = 1.0%):
        - Bars 0..5: 100.0 (flat)
        - Bar 6: 110.0 -> BUY signal at Bar 6 close (no fee yet)
        - Bar 7: 220.0 -> BUY_ENTRY fills at Bar 7 close; 0% gross return, 1% entry fee applied on Bar 7
                         (equity = 10,000 * 0.99 = 9,900.0)
        - Bar 8: 242.0 -> +10% earned while long, 0% fee (equity = 9,900 * 1.10 = 10,890.0)
        - Bar 9: 180.0 -> SMA(2)=211 > SMA(4)=188 (still bullish, earns 180/242 - 1)
        - Bar 10: 150.0 -> SMA(2)=165 < SMA(4)=198 -> SELL signal at Bar 10 close (still long, no fee on Bar 10)
                          (by Bar 10 close, cumulative gross from 220 -> 150 gives equity = 9,900 * (150/220) = 6,750.0)
        - Bar 11: 180.0 -> SELL_EXIT fills at Bar 11 close!
                          Position continues earning +20% (180/150 - 1) through Bar 11 close fill,
                          AND pays 1% exit fee on Bar 11:
                          net_return[11] = 1.20 * 0.99 - 1.0 = 0.188
                          equity[11] = 6,750.0 * 1.20 * 0.99 = 8,019.0
        - Bar 12: 90.0  -> -50% crash AFTER exit fill; position is 0.0 and earns 0.0% on Bar 12!
    """
    closes = [100.0] * 6 + [110.0, 220.0, 242.0, 180.0, 150.0, 180.0, 90.0]
    df = _make_ohlcv_from_closes(closes)

    summary = run_sma_crossover_backtest(
        df,
        interval="1d",
        sma_fast_window=2,
        sma_slow_window=4,
        initial_capital=10_000.0,
        transaction_cost_bps=100.0,
        risk_free_rate_annual=0.02,
    )

    tl = summary.timeline
    assert summary.trade_count == 2
    assert summary.completed_round_trips == 1
    assert summary.trades[0].action == "BUY_ENTRY"
    assert summary.trades[0].execution_timestamp == df["timestamp"].iloc[7].strftime("%Y-%m-%d")
    assert summary.trades[1].action == "SELL_EXIT"
    assert summary.trades[1].signal_timestamp == df["timestamp"].iloc[10].strftime("%Y-%m-%d")
    assert summary.trades[1].execution_timestamp == df["timestamp"].iloc[11].strftime("%Y-%m-%d")
    assert summary.trades[1].reference_close == pytest.approx(180.0)

    # Transaction costs placed ONLY on fill bars (indices 7 and 11).
    expected_costs = [0.0] * len(closes)
    expected_costs[7] = 0.01
    expected_costs[11] = 0.01
    np.testing.assert_allclose(tl["transaction_cost"].to_numpy(), expected_costs, atol=1e-12)

    # Entry fill bar (Bar 7): 0 gross return, -1% net return from fee.
    assert tl["strategy_gross_return"].iloc[7] == pytest.approx(0.0, abs=1e-12)
    assert tl["strategy_net_return"].iloc[7] == pytest.approx(-0.01, abs=1e-12)
    assert tl["equity"].iloc[7] == pytest.approx(9_900.0, abs=1e-6)

    # Signal bar before exit (Bar 10): no fee yet; equity tracks 220 -> 150 move.
    assert tl["signal"].iloc[10] == "SELL"
    assert tl["equity"].iloc[10] == pytest.approx(9_900.0 * (150.0 / 220.0), abs=1e-6)

    # Exit fill bar (Bar 11): earns +20% (150 -> 180) through close fill, then pays 1% exit fee.
    assert tl["earning_position"].iloc[11] == pytest.approx(1.0)
    assert tl["executed_position"].iloc[11] == pytest.approx(0.0)
    assert tl["strategy_gross_return"].iloc[11] == pytest.approx(0.20, abs=1e-9)
    assert tl["strategy_net_return"].iloc[11] == pytest.approx(1.20 * 0.99 - 1.0, abs=1e-9)
    assert tl["equity"].iloc[11] == pytest.approx(8_019.0, abs=1e-6)

    # Post-exit bar (Bar 12): -50% asset drop ignored because position exited at Bar 11 close.
    assert tl["earning_position"].iloc[12] == pytest.approx(0.0)
    assert tl["strategy_gross_return"].iloc[12] == pytest.approx(0.0, abs=1e-12)
    assert tl["strategy_net_return"].iloc[12] == pytest.approx(0.0, abs=1e-12)
    assert tl["equity"].iloc[12] == pytest.approx(8_019.0, abs=1e-6)
    assert summary.final_equity == pytest.approx(8_019.0, abs=1e-6)


def test_backtest_interval_annualization_and_per_bar_risk_free_rate(
    deterministic_ohlcv_df: pd.DataFrame,
) -> None:
    """Verify 1d (252), 1wk (52), and 1mo (12) scale volatility, rf/bar, and Sharpe accurately
    while keeping cumulative total_return and max_drawdown invariant for a given bar series.
    """
    annual_rf = 0.06
    results = {
        iv: run_sma_crossover_backtest(
            deterministic_ohlcv_df,
            interval=iv,
            sma_fast_window=5,
            sma_slow_window=15,
            initial_capital=10_000.0,
            transaction_cost_bps=10.0,
            risk_free_rate_annual=annual_rf,
        )
        for iv in ("1d", "1wk", "1mo")
    }

    assert results["1d"].periods_per_year == 252
    assert results["1wk"].periods_per_year == 52
    assert results["1mo"].periods_per_year == 12

    assert results["1d"].risk_free_rate_per_bar == pytest.approx(annual_rf / 252.0)
    assert results["1wk"].risk_free_rate_per_bar == pytest.approx(annual_rf / 52.0)
    assert results["1mo"].risk_free_rate_per_bar == pytest.approx(annual_rf / 12.0)

    assert results["1d"].total_return == pytest.approx(results["1wk"].total_return)
    assert results["1d"].total_return == pytest.approx(results["1mo"].total_return)
    assert results["1d"].max_drawdown == pytest.approx(results["1wk"].max_drawdown)
    assert results["1d"].max_drawdown == pytest.approx(results["1mo"].max_drawdown)
    assert results["1d"].trade_count == results["1wk"].trade_count == results["1mo"].trade_count

    assert (
        results["1d"].annualized_volatility / np.sqrt(252)
        == pytest.approx(results["1wk"].annualized_volatility / np.sqrt(52))
    )
    assert (
        results["1d"].annualized_volatility / np.sqrt(252)
        == pytest.approx(results["1mo"].annualized_volatility / np.sqrt(12))
    )

    for iv, expected_ppy in (("1d", 252), ("1wk", 52), ("1mo", 12)):
        net_ret = results[iv].timeline["strategy_net_return"]
        excess = net_ret - (annual_rf / expected_ppy)
        expected_sharpe = float((excess.mean() / excess.std(ddof=1)) * np.sqrt(expected_ppy))
        assert results[iv].sharpe_ratio == pytest.approx(expected_sharpe)


def test_backtest_validates_inputs_and_zero_trade_sharpe() -> None:
    flat_df = _make_ohlcv_from_closes([100.0] * 20)
    res = run_sma_crossover_backtest(
        flat_df, interval="1wk", sma_fast_window=3, sma_slow_window=8, risk_free_rate_annual=0.03
    )
    assert res.periods_per_year == 52
    assert res.trade_count == 0
    assert res.sharpe_ratio == 0.0

    with pytest.raises(InvalidRequestError):
        run_sma_crossover_backtest(flat_df.iloc[:6], sma_fast_window=3, sma_slow_window=8)

    with pytest.raises(InvalidRequestError, match="Unsupported interval"):
        run_sma_crossover_backtest(flat_df, interval="5m", sma_fast_window=3, sma_slow_window=8)
