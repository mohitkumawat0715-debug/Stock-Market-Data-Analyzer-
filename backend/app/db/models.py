"""SQLAlchemy 2.x ORM models for watchlists, paper portfolios, quotes, and alerts.

All timestamps are stored as UTC. SQLite has no timezone support, so the
`UTCDateTime` type normalizes values to naive UTC on write and restores an
aware UTC `datetime` on read.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):  # type: ignore[type-arg]
    """DateTime that always round-trips as an aware UTC value."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if value.tzinfo is None:
            return value  # naive values are assumed to already be UTC
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all persisted models."""


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    items: Mapped[list[WatchlistItem]] = relationship(
        back_populates="watchlist",
        cascade="all, delete-orphan",
        order_by="WatchlistItem.id",
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "ticker", name="uq_watchlist_ticker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(12), nullable=False)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")


class Portfolio(Base):
    """A simulated (paper) portfolio. No real money or brokerage is involved."""

    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    starting_cash: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    transactions: Mapped[list[PaperTransaction]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
        order_by="PaperTransaction.id",
    )


class PaperTransaction(Base):
    __tablename__ = "paper_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(12), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # BUY or SELL
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    executed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    price_source: Mapped[str] = mapped_column(String(40), nullable=False, default="user_supplied")
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    portfolio: Mapped[Portfolio] = relationship(back_populates="transactions")


class QuoteSnapshot(Base):
    """One provider quote. `fetched_at` is when we asked; `exchange_timestamp` is the
    provider-reported time of the last trade (may be null or stale)."""

    __tablename__ = "quote_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    prev_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    exchange_timestamp: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    data_source: Mapped[str] = mapped_column(String(8), nullable=False, default="csv")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Last observed condition state; events fire only on a false -> true transition.
    condition_met: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    events: Mapped[list[AlertEvent]] = relationship(
        back_populates="rule",
        cascade="all, delete-orphan",
        order_by="AlertEvent.id",
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    triggered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_signal: Mapped[str | None] = mapped_column(String(12), nullable=True)
    observation_source: Mapped[str] = mapped_column(String(40), nullable=False)
    observation_as_of: Mapped[str | None] = mapped_column(String(40), nullable=True)
    message: Mapped[str] = mapped_column(String(300), nullable=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    rule: Mapped[AlertRule] = relationship(back_populates="events")
