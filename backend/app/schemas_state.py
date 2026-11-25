"""Pydantic request and response models for the stateful Phase 3 endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AlertKindLiteral = Literal[
    "price_above",
    "price_below",
    "rsi_above",
    "rsi_below",
    "sma_crossover_buy",
    "sma_crossover_sell",
]


class WatchlistCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


class WatchlistItemCreate(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=12)
    note: str | None = Field(default=None, max_length=200)


class WatchlistItemOut(BaseModel):
    ticker: str
    note: str | None
    added_at: datetime


class WatchlistOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    items: list[WatchlistItemOut]


class PortfolioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    starting_cash: float = Field(..., gt=0.0, le=1_000_000_000.0)


class TransactionCreate(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=12)
    side: Literal["BUY", "SELL"]
    quantity: float = Field(..., gt=0.0, le=1_000_000_000.0)
    price: float | None = Field(
        default=None,
        gt=0.0,
        description="Optional fill price. If omitted, the latest locally known price is used and its source is recorded.",
    )
    fee: float = Field(default=0.0, ge=0.0, le=1_000_000.0)
    note: str | None = Field(default=None, max_length=200)


class TransactionOut(BaseModel):
    id: int
    ticker: str
    side: str
    quantity: float
    price: float
    fee: float
    executed_at: datetime
    price_source: str
    note: str | None


class PortfolioOut(BaseModel):
    id: int
    name: str
    starting_cash: float
    created_at: datetime


class HoldingOut(BaseModel):
    ticker: str
    quantity: float
    average_cost: float
    cost_basis: float
    market_price: float | None
    market_value: float | None
    unrealized_pnl: float | None
    price_source: str | None
    price_as_of: str | None
    price_is_realtime: bool = False


class PortfolioSummaryOut(BaseModel):
    portfolio: PortfolioOut
    cash: float
    holdings_market_value: float
    total_value: float | None = Field(
        description="Cash plus holdings value; null when any holding has no available price."
    )
    total_pnl: float | None
    total_pnl_pct: float | None
    realized_pnl: float
    unrealized_pnl: float
    total_fees: float
    valuation_complete: bool
    holdings: list[HoldingOut]
    note: str


class QuoteOut(BaseModel):
    ticker: str
    price: float
    open: float | None
    high: float | None
    low: float | None
    prev_close: float | None
    provider: str
    exchange_timestamp: datetime | None
    fetched_at: datetime
    is_realtime: bool = False
    freshness_status: Literal["unknown", "recent", "stale"]
    age_seconds: float | None
    freshness_note: str


class PollStatusOut(BaseModel):
    provider_configured: bool
    polling_enabled: bool
    polling_active: bool
    provider: str | None
    poll_interval_seconds: int
    max_symbols_per_cycle: int
    last_fetched: list[str]
    last_failed: dict[str, str]
    last_skipped_over_cap: list[str]
    last_finished_at: datetime | None
    consecutive_failures: int
    note: str


class PollResultOut(BaseModel):
    fetched: list[str]
    failed: dict[str, str]
    skipped_over_cap: list[str]
    stopped_for_rate_limit: bool


class AlertRuleCreate(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=12)
    kind: AlertKindLiteral
    threshold: float | None = None
    cooldown_minutes: int = Field(default=60, ge=0, le=10_080)
    data_source: Literal["csv", "yahoo"] = "csv"


class AlertRuleOut(BaseModel):
    id: int
    ticker: str
    kind: str
    threshold: float | None
    cooldown_minutes: int
    data_source: str
    active: bool
    condition_met: bool
    last_triggered_at: datetime | None
    created_at: datetime


class AlertRuleUpdate(BaseModel):
    active: bool


class AlertEventOut(BaseModel):
    id: int
    rule_id: int
    ticker: str
    kind: str
    triggered_at: datetime
    observed_value: float | None
    observed_signal: str | None
    observation_source: str
    observation_as_of: str | None
    message: str
    acknowledged: bool


class EvaluationOut(BaseModel):
    evaluated: int
    triggered: int
    suppressed_by_cooldown: int
    errors: list[dict[str, object]]
    new_event_ids: list[int]
