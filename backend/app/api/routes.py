"""FastAPI route handlers kept thin and decoupled from calculation engines."""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, Path, Query

from app.analysis import (
    WARMUP_POLICY_DESCRIPTION,
    append_sma_crossover_signals,
    compute_indicator_dataframe,
    get_periods_per_year,
    run_sma_crossover_backtest,
    summarize_signals,
)
from app.config import Settings, get_settings
from app.exceptions import InvalidRequestError
from app.providers import (
    CSVMarketDataProvider,
    MarketDataProvider,
    MarketDataResult,
    YahooFinanceProvider,
)
from app.providers.base import format_bar_timestamp
from app.schemas import (
    BacktestAssumptions,
    BacktestMetrics,
    BacktestResponse,
    BacktestTrade,
    DataFreshnessMetadata,
    DataSourceLiteral,
    EquityPoint,
    ErrorResponse,
    HealthResponse,
    IndicatorBar,
    IndicatorParameters,
    IndicatorsResponse,
    IntervalLiteral,
    MarketDataResponse,
    OHLCVBar,
)

router = APIRouter()


def get_csv_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> CSVMarketDataProvider:
    """Provide a local CSV market data adapter configured from settings."""
    return CSVMarketDataProvider(settings.sample_csv_dir)


def get_yahoo_provider() -> YahooFinanceProvider:
    """Provide a Yahoo Finance historical market data adapter."""
    return YahooFinanceProvider()


def _select_provider(
    source: DataSourceLiteral,
    csv_provider: CSVMarketDataProvider,
    yahoo_provider: MarketDataProvider,
) -> MarketDataProvider:
    if source == "csv":
        return csv_provider
    if source == "yahoo":
        return yahoo_provider
    raise InvalidRequestError(
        f"Unsupported data source '{source}'. Expected 'csv' or 'yahoo'.",
        details={"source": source},
    )


def _clean_optional_float(value: object, digits: int = 6) -> float | None:
    """Convert pandas/numpy scalars to finite Python floats or None for JSON safety."""
    if value is None or pd.isna(value):
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    return round(numeric, digits)


def _build_metadata(result: MarketDataResult) -> DataFreshnessMetadata:
    return DataFreshnessMetadata(
        ticker=result.ticker,
        interval=result.interval,  # type: ignore[arg-type]
        source=result.source,
        is_realtime=result.is_realtime,
        last_available_timestamp=result.last_available_timestamp,
        bar_count=result.bar_count,
        freshness_note=result.freshness_note,
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Check service health and local CSV dataset availability",
)
def health_check(
    settings: Annotated[Settings, Depends(get_settings)],
    csv_provider: Annotated[CSVMarketDataProvider, Depends(get_csv_provider)],
) -> HealthResponse:
    """Return service status, version, active environment, and available sample tickers."""
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        available_csv_tickers=csv_provider.list_available_tickers(),
        timestamp_utc=datetime.now(timezone.utc),
    )


@router.get(
    "/market-data/{ticker}",
    response_model=MarketDataResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
    tags=["Market Data"],
    summary="Retrieve validated and normalized OHLCV bars",
)
def get_market_data(
    ticker: Annotated[
        str,
        Path(description="Stock ticker symbol, such as AAPL or MSFT.", min_length=1, max_length=12),
    ],
    csv_provider: Annotated[CSVMarketDataProvider, Depends(get_csv_provider)],
    yahoo_provider: Annotated[MarketDataProvider, Depends(get_yahoo_provider)],
    source: Annotated[
        DataSourceLiteral,
        Query(description="Data provider to query: 'csv' (offline local sample) or 'yahoo'."),
    ] = "yahoo",
    start_date: Annotated[
        date | None,
        Query(description="Inclusive ISO-8601 start date (YYYY-MM-DD)."),
    ] = None,
    end_date: Annotated[
        date | None,
        Query(description="Inclusive ISO-8601 end date (YYYY-MM-DD)."),
    ] = None,
    interval: Annotated[
        IntervalLiteral,
        Query(description="Bar aggregation interval: 1d, 1wk, or 1mo."),
    ] = "1d",
) -> MarketDataResponse:
    """Fetch normalized historical OHLCV bars with explicit data provenance metadata."""
    provider = _select_provider(source, csv_provider, yahoo_provider)
    result = provider.fetch_ohlcv(
        ticker,
        start_date=start_date,
        end_date=end_date,
        interval=interval,
    )

    bars = [
        OHLCVBar(
            timestamp=format_bar_timestamp(pd.Timestamp(row.timestamp)),
            open=round(float(row.open), 4),
            high=round(float(row.high), 4),
            low=round(float(row.low), 4),
            close=round(float(row.close), 4),
            volume=round(float(row.volume), 2),
        )
        for row in result.dataframe.itertuples(index=False)
    ]

    return MarketDataResponse(
        metadata=_build_metadata(result),
        bars=bars,
    )


@router.get(
    "/indicators/{ticker}",
    response_model=IndicatorsResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
    tags=["Technical Analysis"],
    summary="Compute technical indicators and educational SMA crossover signals",
)
def get_indicators_and_signals(
    ticker: Annotated[
        str,
        Path(description="Stock ticker symbol, such as AAPL or MSFT.", min_length=1, max_length=12),
    ],
    csv_provider: Annotated[CSVMarketDataProvider, Depends(get_csv_provider)],
    yahoo_provider: Annotated[MarketDataProvider, Depends(get_yahoo_provider)],
    source: Annotated[DataSourceLiteral, Query()] = "yahoo",
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    interval: Annotated[IntervalLiteral, Query()] = "1d",
    sma_fast: Annotated[int, Query(ge=2, le=250, description="Fast SMA window.")] = 10,
    sma_slow: Annotated[int, Query(ge=3, le=500, description="Slow SMA window.")] = 30,
    ema_window: Annotated[int, Query(ge=2, le=250, description="EMA window.")] = 20,
    rsi_window: Annotated[int, Query(ge=2, le=100, description="Wilder RSI window.")] = 14,
    macd_fast: Annotated[int, Query(ge=2, le=100, description="MACD fast EMA window.")] = 12,
    macd_slow: Annotated[int, Query(ge=3, le=200, description="MACD slow EMA window.")] = 26,
    macd_signal: Annotated[int, Query(ge=2, le=100, description="MACD signal EMA window.")] = 9,
    volatility_window: Annotated[
        int, Query(ge=2, le=252, description="Rolling volatility window.")
    ] = 20,
) -> IndicatorsResponse:
    """Compute per-bar returns, SMA, EMA, RSI, MACD, interval-scaled volatility, and signals."""
    periods_per_year = get_periods_per_year(interval)
    provider = _select_provider(source, csv_provider, yahoo_provider)
    result = provider.fetch_ohlcv(
        ticker,
        start_date=start_date,
        end_date=end_date,
        interval=interval,
    )

    indicator_df = compute_indicator_dataframe(
        result.dataframe,
        interval=interval,
        sma_fast_window=sma_fast,
        sma_slow_window=sma_slow,
        ema_window=ema_window,
        rsi_window=rsi_window,
        macd_fast_window=macd_fast,
        macd_slow_window=macd_slow,
        macd_signal_window=macd_signal,
        volatility_window=volatility_window,
    )
    enriched_df = append_sma_crossover_signals(indicator_df)
    summary = summarize_signals(enriched_df)

    bars = [
        IndicatorBar(
            timestamp=format_bar_timestamp(pd.Timestamp(row.timestamp)),
            open=round(float(row.open), 4),
            high=round(float(row.high), 4),
            low=round(float(row.low), 4),
            close=round(float(row.close), 4),
            volume=round(float(row.volume), 2),
            bar_return=_clean_optional_float(row.bar_return, 6),
            sma_fast=_clean_optional_float(row.sma_fast, 4),
            sma_slow=_clean_optional_float(row.sma_slow, 4),
            ema=_clean_optional_float(row.ema, 4),
            rsi=_clean_optional_float(row.rsi, 4),
            macd_line=_clean_optional_float(row.macd_line, 4),
            macd_signal=_clean_optional_float(row.macd_signal, 4),
            macd_histogram=_clean_optional_float(row.macd_histogram, 4),
            rolling_volatility=_clean_optional_float(row.rolling_volatility, 6),
            signal=row.signal,
            regime=row.regime,
        )
        for row in enriched_df.itertuples(index=False)
    ]

    return IndicatorsResponse(
        metadata=_build_metadata(result),
        parameters=IndicatorParameters(
            interval=interval,
            periods_per_year=periods_per_year,
            sma_fast_window=sma_fast,
            sma_slow_window=sma_slow,
            ema_window=ema_window,
            rsi_window=rsi_window,
            macd_fast_window=macd_fast,
            macd_slow_window=macd_slow,
            macd_signal_window=macd_signal,
            volatility_window=volatility_window,
            warmup_policy=WARMUP_POLICY_DESCRIPTION,
        ),
        signal_summary=summary,
        bars=bars,
    )


@router.get(
    "/backtest/{ticker}",
    response_model=BacktestResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
    tags=["Backtesting"],
    summary="Run a 1-bar delayed long-only SMA crossover backtest",
)
def get_backtest_results(
    ticker: Annotated[
        str,
        Path(description="Stock ticker symbol, such as AAPL or MSFT.", min_length=1, max_length=12),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    csv_provider: Annotated[CSVMarketDataProvider, Depends(get_csv_provider)],
    yahoo_provider: Annotated[MarketDataProvider, Depends(get_yahoo_provider)],
    source: Annotated[DataSourceLiteral, Query()] = "yahoo",
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    interval: Annotated[IntervalLiteral, Query()] = "1d",
    sma_fast: Annotated[int, Query(ge=2, le=250)] = 10,
    sma_slow: Annotated[int, Query(ge=3, le=500)] = 30,
    initial_capital: Annotated[float, Query(gt=0.0, le=100_000_000.0)] = 10_000.0,
    transaction_cost_bps: Annotated[float | None, Query(ge=0.0, le=1_000.0)] = None,
    risk_free_rate: Annotated[float | None, Query(ge=-0.10, le=0.50)] = None,
) -> BacktestResponse:
    """Run an educational SMA crossover backtest with interval-aware annualization assumptions."""
    provider = _select_provider(source, csv_provider, yahoo_provider)
    result = provider.fetch_ohlcv(
        ticker,
        start_date=start_date,
        end_date=end_date,
        interval=interval,
    )

    effective_cost_bps = (
        settings.default_transaction_cost_bps
        if transaction_cost_bps is None
        else transaction_cost_bps
    )
    effective_rf = (
        settings.default_risk_free_rate if risk_free_rate is None else risk_free_rate
    )

    bt = run_sma_crossover_backtest(
        result.dataframe,
        interval=interval,
        sma_fast_window=sma_fast,
        sma_slow_window=sma_slow,
        initial_capital=initial_capital,
        transaction_cost_bps=effective_cost_bps,
        risk_free_rate_annual=effective_rf,
    )

    trades = [
        BacktestTrade(
            execution_timestamp=t.execution_timestamp,
            signal_timestamp=t.signal_timestamp,
            action=t.action,  # type: ignore[arg-type]
            reference_close=round(t.reference_close, 4),
            cost_bps_applied=round(t.cost_bps_applied, 2),
        )
        for t in bt.trades
    ]

    equity_curve = [
        EquityPoint(
            timestamp=format_bar_timestamp(pd.Timestamp(row.timestamp)),
            close=round(float(row.close), 4),
            signal=row.signal,
            desired_position=round(float(row.desired_position), 2),
            executed_position=round(float(row.executed_position), 2),
            earning_position=round(float(row.earning_position), 2),
            strategy_net_return=round(float(row.strategy_net_return), 6),
            equity=round(float(row.equity), 2),
            drawdown=round(float(row.drawdown), 6),
        )
        for row in bt.timeline.itertuples(index=False)
    ]

    return BacktestResponse(
        metadata=_build_metadata(result),
        assumptions=BacktestAssumptions(
            interval=interval,
            periods_per_year=bt.periods_per_year,
            sma_fast_window=bt.sma_fast_window,
            sma_slow_window=bt.sma_slow_window,
            initial_capital=round(bt.initial_capital, 2),
            execution_delay_bars=bt.execution_delay_bars,
            execution_fill_convention="next_bar_close",
            transaction_cost_bps=round(bt.transaction_cost_bps, 2),
            risk_free_rate_annual=round(bt.risk_free_rate_annual, 4),
            risk_free_rate_per_bar=round(bt.risk_free_rate_per_bar, 8),
            methodology_note=(
                f"Long-only SMA crossover simulation on {interval} bars "
                f"({bt.periods_per_year} periods per year) using a next-bar-close fill convention "
                "(execution_delay_bars = 1). Signals calculated from bar t close fill at bar t+1 close: "
                "the bar t to t+1 return belongs to the position held before the fill, new entries begin "
                "earning close-to-close returns on bar t+2, exits earn through the bar t+1 close fill and "
                f"stop thereafter, and {bt.transaction_cost_bps:.2f} bps transaction costs apply at each fill event. "
                f"Annualized volatility and Sharpe ratio scale by sqrt({bt.periods_per_year}), "
                f"converting the {bt.risk_free_rate_annual * 100:.2f}% annual risk-free rate "
                f"to a per-bar rate of {bt.risk_free_rate_annual / bt.periods_per_year:.6f}."
            ),
        ),
        metrics=BacktestMetrics(
            initial_capital=round(bt.initial_capital, 2),
            final_equity=round(bt.final_equity, 2),
            total_return=round(bt.total_return, 6),
            total_return_pct=round(bt.total_return_pct, 4),
            benchmark_buy_and_hold_return=round(bt.benchmark_buy_and_hold_return, 6),
            annualized_volatility=round(bt.annualized_volatility, 6),
            max_drawdown=round(bt.max_drawdown, 6),
            sharpe_ratio=round(bt.sharpe_ratio, 4),
            trade_count=bt.trade_count,
            completed_round_trips=bt.completed_round_trips,
        ),
        trades=trades,
        equity_curve=equity_curve,
    )
