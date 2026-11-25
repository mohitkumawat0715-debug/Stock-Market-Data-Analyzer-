"""Alert rule evaluation with edge detection and cooldown suppression.

Rules fire on a false -> true transition of their condition, at most once per
`cooldown_minutes`. If a transition is suppressed by the cooldown, the rule's
stored state stays "not met", so it can still fire once the cooldown expires
if the condition is still true. Provider failures never change rule state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import append_sma_crossover_signals, compute_indicator_dataframe
from app.db.models import AlertEvent, AlertRule
from app.exceptions import AnalyzerError, InvalidRequestError
from app.providers.base import MarketDataProvider, format_bar_timestamp
from app.services.pricing import PriceResolver

PRICE_KINDS = {"price_above", "price_below"}
RSI_KINDS = {"rsi_above", "rsi_below"}
SIGNAL_KINDS = {"sma_crossover_buy", "sma_crossover_sell"}
ALL_KINDS = PRICE_KINDS | RSI_KINDS | SIGNAL_KINDS
THRESHOLD_KINDS = PRICE_KINDS | RSI_KINDS


@dataclass(frozen=True)
class Observation:
    price: float | None = None
    rsi: float | None = None
    signal: str | None = None
    source: str = ""
    as_of: str | None = None


class Observer(Protocol):
    def observe(self, rule: AlertRule) -> Observation: ...


def validate_rule_definition(kind: str, threshold: float | None, data_source: str) -> None:
    if kind not in ALL_KINDS:
        raise InvalidRequestError(
            f"Unsupported alert kind '{kind}'.", details={"supported": sorted(ALL_KINDS)}
        )
    if kind in THRESHOLD_KINDS and threshold is None:
        raise InvalidRequestError(f"Alert kind '{kind}' requires a threshold.")
    if kind in RSI_KINDS and not (0.0 <= float(threshold) <= 100.0):  # type: ignore[arg-type]
        raise InvalidRequestError("RSI thresholds must be between 0 and 100.")
    if kind in PRICE_KINDS and float(threshold) <= 0.0:  # type: ignore[arg-type]
        raise InvalidRequestError("Price thresholds must be positive.")
    if kind in SIGNAL_KINDS and threshold is not None:
        raise InvalidRequestError(f"Alert kind '{kind}' does not use a threshold.")
    if data_source not in ("csv", "yahoo"):
        raise InvalidRequestError("data_source must be 'csv' or 'yahoo'.")


def condition_is_met(rule: AlertRule, obs: Observation) -> bool:
    if rule.kind == "price_above":
        return obs.price is not None and obs.price >= float(rule.threshold)  # type: ignore[arg-type]
    if rule.kind == "price_below":
        return obs.price is not None and obs.price <= float(rule.threshold)  # type: ignore[arg-type]
    if rule.kind == "rsi_above":
        return obs.rsi is not None and obs.rsi >= float(rule.threshold)  # type: ignore[arg-type]
    if rule.kind == "rsi_below":
        return obs.rsi is not None and obs.rsi <= float(rule.threshold)  # type: ignore[arg-type]
    if rule.kind == "sma_crossover_buy":
        return obs.signal == "BUY"
    if rule.kind == "sma_crossover_sell":
        return obs.signal == "SELL"
    return False


def describe_event(rule: AlertRule, obs: Observation) -> str:
    base = f"{rule.ticker}: {rule.kind.replace('_', ' ')}"
    if rule.kind in THRESHOLD_KINDS:
        base += f" {rule.threshold:g}"
    if rule.kind in PRICE_KINDS and obs.price is not None:
        base += f" (observed {obs.price:.2f})"
    elif rule.kind in RSI_KINDS and obs.rsi is not None:
        base += f" (observed RSI {obs.rsi:.1f})"
    return f"{base} [{obs.source}, as of {obs.as_of}]. Educational signal, not advice."[:300]


class MarketObserver:
    """Builds observations from stored quotes / CSV prices and historical indicators."""

    def __init__(
        self,
        session: Session,
        csv_provider: MarketDataProvider,
        provider_for_source: Callable[[str], MarketDataProvider],
    ) -> None:
        self._prices = PriceResolver(session, csv_provider)
        self._provider_for_source = provider_for_source

    def observe(self, rule: AlertRule) -> Observation:
        if rule.kind in PRICE_KINDS:
            info = self._prices.resolve(rule.ticker)
            if info is None:
                raise InvalidRequestError(f"No price available for '{rule.ticker}'.")
            return Observation(price=info.price, source=info.source, as_of=info.as_of)

        provider = self._provider_for_source(rule.data_source)
        result = provider.fetch_ohlcv(rule.ticker, interval="1d")
        frame = append_sma_crossover_signals(compute_indicator_dataframe(result.dataframe))
        last = frame.iloc[-1]
        rsi = None if pd.isna(last["rsi"]) else float(last["rsi"])
        return Observation(
            price=float(last["close"]),
            rsi=rsi,
            signal=str(last["signal"]),
            source=result.source,
            as_of=format_bar_timestamp(pd.Timestamp(last["timestamp"])),
        )


@dataclass
class EvaluationSummary:
    evaluated: int = 0
    triggered: int = 0
    suppressed_by_cooldown: int = 0
    errors: list[dict[str, object]] = field(default_factory=list)
    new_event_ids: list[int] = field(default_factory=list)


def evaluate_alert_rules(
    session: Session, observer: Observer, *, now: datetime | None = None
) -> EvaluationSummary:
    """Evaluate all active rules once and persist events and rule state."""
    current = now or datetime.now(timezone.utc)
    summary = EvaluationSummary()
    rules = session.scalars(select(AlertRule).where(AlertRule.active.is_(True))).all()
    for rule in rules:
        try:
            obs = observer.observe(rule)
        except AnalyzerError as exc:
            summary.errors.append(
                {"rule_id": rule.id, "ticker": rule.ticker, "error_code": exc.error_code,
                 "message": exc.message}
            )
            continue
        summary.evaluated += 1
        met = condition_is_met(rule, obs)
        if not met:
            rule.condition_met = False
            continue
        if rule.condition_met:
            continue  # still true from an earlier evaluation: no duplicate event
        in_cooldown = rule.last_triggered_at is not None and current < rule.last_triggered_at + timedelta(
            minutes=rule.cooldown_minutes
        )
        if in_cooldown:
            summary.suppressed_by_cooldown += 1
            continue  # leave condition_met False so it can fire after the cooldown
        event = AlertEvent(
            rule_id=rule.id,
            triggered_at=current,
            observed_value=obs.price if rule.kind in PRICE_KINDS else obs.rsi,
            observed_signal=obs.signal,
            observation_source=obs.source,
            observation_as_of=obs.as_of,
            message=describe_event(rule, obs),
        )
        session.add(event)
        session.flush()
        rule.condition_met = True
        rule.last_triggered_at = current
        summary.triggered += 1
        summary.new_event_ids.append(event.id)
    session.commit()
    return summary
