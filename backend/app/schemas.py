"""Pydantic schemas for FastAPI request validation and response serialization."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EDUCATIONAL_DISCLAIMER = (
    "For educational and software demonstration purposes only. Historical data, "
    "technical indicators, crossover signals, and backtest metrics do not "
    "constitute financial advice, price predictions, or trade recommendations."
)

DataSourceLiteral = Literal["csv", "yahoo"]
IntervalLiteral = Literal["1d", "1wk", "1mo"]
SignalLiteral = Literal["WARMUP", "BUY", "SELL", "NEUTRAL"]
RegimeLiteral = Literal["WARMUP", "BULLISH", "BEARISH", "NEUTRAL"]


class ErrorResponse(BaseModel):
    """Standardized error payload returned for all domain and validation errors."""

    error_code: str = Field(..., description="Machine-readable error identifier.")
    message: str = Field(..., description="Human-readable explanation of the issue.")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured context describing invalid fields or rows.",
    )


class HealthResponse(BaseModel):
    """Service liveness and configuration summary."""

    status: Literal["ok"] = "ok"
    service: str
    version: str
    environment: str
    available_csv_tickers: list[str]
    timestamp_utc: datetime


class DataFreshnessMetadata(BaseModel):
    """Explicit data provenance and latency disclosure included in responses."""

    ticker: str
    interval: IntervalLiteral
    source: str = Field(
        ..., description="Underlying adapter identifier (local_csv or yahoo_finance_historical)."
    )
    is_realtime: bool = Field(
        default=False,
        description="Always false in Phase 1; historical and delayed bars are never real-time.",
    )
    last_available_timestamp: str = Field(
        ..., description="ISO-8601 timestamp of the latest bar present in the returned dataset."
    )
    bar_count: int = Field(..., ge=1)
    freshness_note: str


class OHLCVBar(BaseModel):
    """Single normalized historical market bar."""

    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketDataResponse(BaseModel):
    """Normalized OHLCV market data response."""

    metadata: DataFreshnessMetadata
    disclaimer: str = EDUCATIONAL_DISCLAIMER
    bars: list[OHLCVBar]


class IndicatorParameters(BaseModel):
    """Configuration parameters used to compute indicators and signals."""

    interval: IntervalLiteral
    periods_per_year: int = Field(
        ..., description="Annualization factor for the selected interval (252 for 1d, 52 for 1wk, 12 for 1mo)."
    )
    sma_fast_window: int
    sma_slow_window: int
    ema_window: int
    rsi_window: int
    macd_fast_window: int
    macd_slow_window: int
    macd_signal_window: int
    volatility_window: int
    warmup_policy: str


class IndicatorBar(BaseModel):
    """Market bar enriched with technical indicators and educational signals."""

    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_return: float | None = Field(
        default=None,
        description="Simple close-to-close return over the selected bar interval.",
    )
    sma_fast: float | None = None
    sma_slow: float | None = None
    ema: float | None = None
    rsi: float | None = None
    macd_line: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    rolling_volatility: float | None = None
    signal: SignalLiteral
    regime: RegimeLiteral


class IndicatorsResponse(BaseModel):
    """Technical indicators and educational crossover signal response."""

    metadata: DataFreshnessMetadata
    parameters: IndicatorParameters
    signal_summary: dict[str, int]
    disclaimer: str = EDUCATIONAL_DISCLAIMER
    bars: list[IndicatorBar]


class BacktestAssumptions(BaseModel):
    """Explicit modeling assumptions governing the historical simulation."""

    strategy_name: str = "Long-Only SMA Crossover"
    interval: IntervalLiteral
    periods_per_year: int = Field(
        ..., description="Annualization periods per year for the selected interval (252 for 1d, 52 for 1wk, 12 for 1mo)."
    )
    sma_fast_window: int
    sma_slow_window: int
    initial_capital: float
    execution_delay_bars: int = 1
    execution_fill_convention: Literal["next_bar_close"] = Field(
        default="next_bar_close",
        description="Signals at bar t close fill at bar t+1 close; post-fill returns start on bar t+2.",
    )
    transaction_cost_bps: float
    risk_free_rate_annual: float
    risk_free_rate_per_bar: float
    methodology_note: str


class BacktestMetrics(BaseModel):
    """Headline performance and risk metrics for the simulated strategy."""

    initial_capital: float
    final_equity: float
    total_return: float = Field(
        ..., description="Cumulative net return as a decimal ratio (0.12 = +12.0%)."
    )
    total_return_pct: float = Field(
        ..., description="Cumulative net return expressed in percentage points."
    )
    benchmark_buy_and_hold_return: float = Field(
        ..., description="Buy-and-hold close-to-close return over the same sample."
    )
    annualized_volatility: float = Field(
        ..., description="Annualized standard deviation of per-bar net strategy returns scaled by sqrt(periods_per_year)."
    )
    max_drawdown: float = Field(
        ..., description="Worst peak-to-trough equity decline as a decimal ratio (<= 0.0)."
    )
    sharpe_ratio: float = Field(
        ..., description="Annualized excess return per unit of strategy return volatility."
    )
    trade_count: int = Field(
        ..., description="Total executed position change orders (entries plus exits)."
    )
    completed_round_trips: int = Field(
        ..., description="Number of fully closed entry-to-exit long positions."
    )


class BacktestTrade(BaseModel):
    """Individual executed order generated after the 1-bar signal delay."""

    execution_timestamp: str
    signal_timestamp: str
    action: Literal["BUY_ENTRY", "SELL_EXIT"]
    reference_close: float
    cost_bps_applied: float


class EquityPoint(BaseModel):
    """Per-bar strategy equity and position state."""

    timestamp: str
    close: float
    signal: SignalLiteral
    desired_position: float = Field(
        ..., description="Target position evaluated from this bar's close."
    )
    executed_position: float = Field(
        ..., description="Actual position held after this bar's close fill."
    )
    earning_position: float = Field(
        ..., description="Position held entering this bar (before any close fill), earning this bar's return."
    )
    strategy_net_return: float
    equity: float
    drawdown: float


class BacktestResponse(BaseModel):
    """Complete SMA crossover backtest response."""

    metadata: DataFreshnessMetadata
    assumptions: BacktestAssumptions
    metrics: BacktestMetrics
    trades: list[BacktestTrade]
    equity_curve: list[EquityPoint]
    disclaimer: str = EDUCATIONAL_DISCLAIMER
