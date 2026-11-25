"""Stateful endpoints: watchlists, paper portfolios, quotes, and alerts."""

from __future__ import annotations

from typing import Annotated, Iterator

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes import get_csv_provider, get_yahoo_provider
from app.config import Settings, get_settings
from app.db.models import (
    AlertEvent,
    AlertRule,
    PaperTransaction,
    Portfolio,
    QuoteSnapshot,
    Watchlist,
    WatchlistItem,
)
from app.exceptions import (
    ConflictError,
    InvalidRequestError,
    ProviderNotConfiguredError,
    ResourceNotFoundError,
)
from app.providers import CSVMarketDataProvider, MarketDataProvider
from app.providers.csv_provider import validate_ticker_symbol
from app.quotes.base import QuoteProvider, describe_freshness
from app.schemas_state import (
    AlertEventOut,
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
    EvaluationOut,
    HoldingOut,
    PollResultOut,
    PollStatusOut,
    PortfolioCreate,
    PortfolioOut,
    PortfolioSummaryOut,
    QuoteOut,
    TransactionCreate,
    TransactionOut,
    WatchlistCreate,
    WatchlistItemCreate,
    WatchlistItemOut,
    WatchlistOut,
)
from app.services.alerts import MarketObserver, evaluate_alert_rules, validate_rule_definition
from app.services.polling import PollStatus, poll_quotes_once
from app.services.portfolio import EPSILON, compute_portfolio_state
from app.services.pricing import PriceResolver, latest_quote

state_router = APIRouter()


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def _get_or_404(session: Session, model: type, ident: int, label: str):  # type: ignore[no-untyped-def]
    obj = session.get(model, ident)
    if obj is None:
        raise ResourceNotFoundError(f"{label} {ident} was not found.", details={"id": ident})
    return obj


def _commit_or_conflict(session: Session, message: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(message) from exc


# ---------------------------------------------------------------- watchlists
def _watchlist_out(wl: Watchlist) -> WatchlistOut:
    return WatchlistOut(
        id=wl.id,
        name=wl.name,
        created_at=wl.created_at,
        items=[
            WatchlistItemOut(ticker=i.ticker, note=i.note, added_at=i.added_at) for i in wl.items
        ],
    )


@state_router.post("/watchlists", response_model=WatchlistOut, status_code=201, tags=["Watchlists"])
def create_watchlist(body: WatchlistCreate, session: SessionDep) -> WatchlistOut:
    wl = Watchlist(name=body.name.strip())
    session.add(wl)
    _commit_or_conflict(session, f"A watchlist named '{body.name}' already exists.")
    return _watchlist_out(wl)


@state_router.get("/watchlists", response_model=list[WatchlistOut], tags=["Watchlists"])
def list_watchlists(session: SessionDep) -> list[WatchlistOut]:
    return [_watchlist_out(w) for w in session.scalars(select(Watchlist).order_by(Watchlist.id))]


@state_router.delete("/watchlists/{watchlist_id}", status_code=204, tags=["Watchlists"])
def delete_watchlist(watchlist_id: int, session: SessionDep) -> Response:
    session.delete(_get_or_404(session, Watchlist, watchlist_id, "Watchlist"))
    session.commit()
    return Response(status_code=204)


@state_router.post(
    "/watchlists/{watchlist_id}/items", response_model=WatchlistOut, status_code=201,
    tags=["Watchlists"],
)
def add_watchlist_item(
    watchlist_id: int, body: WatchlistItemCreate, session: SessionDep
) -> WatchlistOut:
    wl = _get_or_404(session, Watchlist, watchlist_id, "Watchlist")
    ticker = validate_ticker_symbol(body.ticker)
    wl.items.append(WatchlistItem(ticker=ticker, note=body.note))
    _commit_or_conflict(session, f"'{ticker}' is already in this watchlist.")
    return _watchlist_out(wl)


@state_router.delete(
    "/watchlists/{watchlist_id}/items/{ticker}", response_model=WatchlistOut, tags=["Watchlists"]
)
def remove_watchlist_item(watchlist_id: int, ticker: str, session: SessionDep) -> WatchlistOut:
    wl = _get_or_404(session, Watchlist, watchlist_id, "Watchlist")
    symbol = validate_ticker_symbol(ticker)
    item = next((i for i in wl.items if i.ticker == symbol), None)
    if item is None:
        raise ResourceNotFoundError(f"'{symbol}' is not in this watchlist.")
    wl.items.remove(item)
    session.commit()
    return _watchlist_out(wl)


# ---------------------------------------------------------------- portfolios
def _portfolio_out(p: Portfolio) -> PortfolioOut:
    return PortfolioOut(
        id=p.id, name=p.name, starting_cash=p.starting_cash, created_at=p.created_at
    )


def _tx_out(t: PaperTransaction) -> TransactionOut:
    return TransactionOut(
        id=t.id, ticker=t.ticker, side=t.side, quantity=t.quantity, price=t.price, fee=t.fee,
        executed_at=t.executed_at, price_source=t.price_source, note=t.note,
    )


@state_router.post("/portfolios", response_model=PortfolioOut, status_code=201, tags=["Portfolios"])
def create_portfolio(body: PortfolioCreate, session: SessionDep) -> PortfolioOut:
    p = Portfolio(name=body.name.strip(), starting_cash=body.starting_cash)
    session.add(p)
    _commit_or_conflict(session, f"A portfolio named '{body.name}' already exists.")
    return _portfolio_out(p)


@state_router.get("/portfolios", response_model=list[PortfolioOut], tags=["Portfolios"])
def list_portfolios(session: SessionDep) -> list[PortfolioOut]:
    return [_portfolio_out(p) for p in session.scalars(select(Portfolio).order_by(Portfolio.id))]


@state_router.delete("/portfolios/{portfolio_id}", status_code=204, tags=["Portfolios"])
def delete_portfolio(portfolio_id: int, session: SessionDep) -> Response:
    session.delete(_get_or_404(session, Portfolio, portfolio_id, "Portfolio"))
    session.commit()
    return Response(status_code=204)


@state_router.post(
    "/portfolios/{portfolio_id}/transactions", response_model=TransactionOut, status_code=201,
    tags=["Portfolios"],
)
def add_transaction(
    portfolio_id: int,
    body: TransactionCreate,
    session: SessionDep,
    csv_provider: Annotated[CSVMarketDataProvider, Depends(get_csv_provider)],
) -> TransactionOut:
    """Record a simulated trade. No orders are sent anywhere; this is paper accounting only."""
    portfolio = _get_or_404(session, Portfolio, portfolio_id, "Portfolio")
    ticker = validate_ticker_symbol(body.ticker)
    price, price_source = body.price, "user_supplied"
    if price is None:
        info = PriceResolver(session, csv_provider).resolve(ticker)
        if info is None:
            raise InvalidRequestError(
                f"No price is available for '{ticker}'; supply `price` explicitly.",
                details={"ticker": ticker},
            )
        price, price_source = info.price, info.source
    tx = PaperTransaction(
        portfolio_id=portfolio.id, ticker=ticker, side=body.side, quantity=body.quantity,
        price=price, fee=body.fee, price_source=price_source, note=body.note,
    )
    # Validate the full replay (overselling, negative cash) before persisting.
    compute_portfolio_state(portfolio.starting_cash, [*portfolio.transactions, tx])
    portfolio.transactions.append(tx)
    session.commit()
    return _tx_out(tx)


@state_router.get(
    "/portfolios/{portfolio_id}/transactions", response_model=list[TransactionOut],
    tags=["Portfolios"],
)
def list_transactions(portfolio_id: int, session: SessionDep) -> list[TransactionOut]:
    portfolio = _get_or_404(session, Portfolio, portfolio_id, "Portfolio")
    return [_tx_out(t) for t in portfolio.transactions]


@state_router.get(
    "/portfolios/{portfolio_id}", response_model=PortfolioSummaryOut, tags=["Portfolios"]
)
def portfolio_summary(
    portfolio_id: int,
    session: SessionDep,
    csv_provider: Annotated[CSVMarketDataProvider, Depends(get_csv_provider)],
) -> PortfolioSummaryOut:
    portfolio = _get_or_404(session, Portfolio, portfolio_id, "Portfolio")
    state = compute_portfolio_state(portfolio.starting_cash, portfolio.transactions)
    resolver = PriceResolver(session, csv_provider)

    holdings: list[HoldingOut] = []
    market_total, unrealized, complete = 0.0, 0.0, True
    for pos in state.open_positions():
        info = resolver.resolve(pos.ticker)
        if info is None:
            complete = False
            holdings.append(HoldingOut(
                ticker=pos.ticker, quantity=pos.quantity, average_cost=pos.average_cost,
                cost_basis=pos.cost_basis, market_price=None, market_value=None,
                unrealized_pnl=None, price_source=None, price_as_of=None,
            ))
            continue
        value = pos.quantity * info.price
        pnl = value - pos.cost_basis
        market_total += value
        unrealized += pnl
        holdings.append(HoldingOut(
            ticker=pos.ticker, quantity=pos.quantity, average_cost=pos.average_cost,
            cost_basis=pos.cost_basis, market_price=info.price, market_value=value,
            unrealized_pnl=pnl, price_source=info.source, price_as_of=info.as_of,
        ))

    total_value = state.cash + market_total if complete else None
    total_pnl = total_value - portfolio.starting_cash if total_value is not None else None
    return PortfolioSummaryOut(
        portfolio=_portfolio_out(portfolio),
        cash=state.cash,
        holdings_market_value=market_total,
        total_value=total_value,
        total_pnl=total_pnl,
        total_pnl_pct=(
            total_pnl / portfolio.starting_cash * 100.0 if total_pnl is not None else None
        ),
        realized_pnl=state.realized_pnl,
        unrealized_pnl=unrealized,
        total_fees=state.total_fees,
        valuation_complete=complete,
        holdings=holdings,
        note=(
            "Simulated paper trading. Holdings are valued with the latest locally stored quote "
            "or the last CSV close, labeled per holding; none is guaranteed real-time. "
            "Average-cost method; fees are included in cost basis and realized P&L."
        ),
    )


# -------------------------------------------------------------------- quotes
def _quote_out(snapshot: QuoteSnapshot, recent_minutes: int) -> QuoteOut:
    fresh = describe_freshness(
        snapshot.exchange_timestamp, snapshot.fetched_at, recent_minutes=recent_minutes
    )
    return QuoteOut(
        ticker=snapshot.ticker, price=snapshot.price, open=snapshot.open, high=snapshot.high,
        low=snapshot.low, prev_close=snapshot.prev_close, provider=snapshot.provider,
        exchange_timestamp=snapshot.exchange_timestamp, fetched_at=snapshot.fetched_at,
        is_realtime=False, freshness_status=fresh.status, age_seconds=fresh.age_seconds,
        freshness_note=fresh.note,
    )


@state_router.get("/quotes/status", response_model=PollStatusOut, tags=["Quotes"])
def quote_status(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> PollStatusOut:
    provider: QuoteProvider | None = request.app.state.quote_provider
    status: PollStatus = request.app.state.poll_status
    last = status.last_result
    return PollStatusOut(
        provider_configured=provider is not None,
        polling_enabled=settings.quote_polling_enabled,
        polling_active=getattr(request.app.state, "polling_task", None) is not None,
        provider=provider.name if provider else None,
        poll_interval_seconds=settings.quote_poll_interval_seconds,
        max_symbols_per_cycle=settings.quote_max_symbols_per_cycle,
        last_fetched=last.fetched if last else [],
        last_failed=last.failed if last else {},
        last_skipped_over_cap=last.skipped_over_cap if last else [],
        last_finished_at=last.finished_at if last else None,
        consecutive_failures=status.consecutive_failures,
        note=(
            "Quote polling is optional. Without FINNHUB_API_KEY the app runs fully offline on "
            "CSV data. Polled quotes are not guaranteed real-time."
        ),
    )


@state_router.post("/quotes/poll", response_model=PollResultOut, tags=["Quotes"])
def poll_now(
    request: Request, session: SessionDep, settings: Annotated[Settings, Depends(get_settings)]
) -> PollResultOut:
    provider: QuoteProvider | None = request.app.state.quote_provider
    if provider is None:
        raise ProviderNotConfiguredError(
            "No quote provider is configured. Set FINNHUB_API_KEY to enable polling; "
            "offline CSV operation is unaffected."
        )
    result = poll_quotes_once(session, provider, max_symbols=settings.quote_max_symbols_per_cycle)
    request.app.state.poll_status.last_result = result
    return PollResultOut(
        fetched=result.fetched, failed=result.failed, skipped_over_cap=result.skipped_over_cap,
        stopped_for_rate_limit=result.stopped_for_rate_limit,
    )


@state_router.get("/quotes/{ticker}", response_model=QuoteOut, tags=["Quotes"])
def get_latest_quote(
    ticker: str, session: SessionDep, settings: Annotated[Settings, Depends(get_settings)]
) -> QuoteOut:
    symbol = validate_ticker_symbol(ticker)
    snapshot = latest_quote(session, symbol)
    if snapshot is None:
        raise ResourceNotFoundError(
            f"No stored quote for '{symbol}'. Quotes exist only after polling is configured.",
            details={"ticker": symbol},
        )
    return _quote_out(snapshot, settings.quote_recent_minutes)


# -------------------------------------------------------------------- alerts
def _rule_out(r: AlertRule) -> AlertRuleOut:
    return AlertRuleOut(
        id=r.id, ticker=r.ticker, kind=r.kind, threshold=r.threshold,
        cooldown_minutes=r.cooldown_minutes, data_source=r.data_source, active=r.active,
        condition_met=r.condition_met, last_triggered_at=r.last_triggered_at,
        created_at=r.created_at,
    )


def _event_out(e: AlertEvent) -> AlertEventOut:
    return AlertEventOut(
        id=e.id, rule_id=e.rule_id, ticker=e.rule.ticker, kind=e.rule.kind,
        triggered_at=e.triggered_at, observed_value=e.observed_value,
        observed_signal=e.observed_signal, observation_source=e.observation_source,
        observation_as_of=e.observation_as_of, message=e.message, acknowledged=e.acknowledged,
    )


@state_router.post("/alerts/rules", response_model=AlertRuleOut, status_code=201, tags=["Alerts"])
def create_alert_rule(body: AlertRuleCreate, session: SessionDep) -> AlertRuleOut:
    ticker = validate_ticker_symbol(body.ticker)
    validate_rule_definition(body.kind, body.threshold, body.data_source)
    rule = AlertRule(
        ticker=ticker, kind=body.kind, threshold=body.threshold,
        cooldown_minutes=body.cooldown_minutes, data_source=body.data_source,
    )
    session.add(rule)
    session.commit()
    return _rule_out(rule)


@state_router.get("/alerts/rules", response_model=list[AlertRuleOut], tags=["Alerts"])
def list_alert_rules(session: SessionDep) -> list[AlertRuleOut]:
    return [_rule_out(r) for r in session.scalars(select(AlertRule).order_by(AlertRule.id))]


@state_router.patch("/alerts/rules/{rule_id}", response_model=AlertRuleOut, tags=["Alerts"])
def update_alert_rule(rule_id: int, body: AlertRuleUpdate, session: SessionDep) -> AlertRuleOut:
    rule = _get_or_404(session, AlertRule, rule_id, "Alert rule")
    rule.active = body.active
    if not body.active:
        rule.condition_met = False
    session.commit()
    return _rule_out(rule)


@state_router.delete("/alerts/rules/{rule_id}", status_code=204, tags=["Alerts"])
def delete_alert_rule(rule_id: int, session: SessionDep) -> Response:
    session.delete(_get_or_404(session, AlertRule, rule_id, "Alert rule"))
    session.commit()
    return Response(status_code=204)


@state_router.post("/alerts/evaluate", response_model=EvaluationOut, tags=["Alerts"])
def evaluate_now(
    session: SessionDep,
    csv_provider: Annotated[CSVMarketDataProvider, Depends(get_csv_provider)],
    yahoo_provider: Annotated[MarketDataProvider, Depends(get_yahoo_provider)],
) -> EvaluationOut:
    observer = MarketObserver(
        session, csv_provider, lambda src: csv_provider if src == "csv" else yahoo_provider
    )
    summary = evaluate_alert_rules(session, observer)
    return EvaluationOut(
        evaluated=summary.evaluated, triggered=summary.triggered,
        suppressed_by_cooldown=summary.suppressed_by_cooldown, errors=summary.errors,
        new_event_ids=summary.new_event_ids,
    )


@state_router.get("/alerts/events", response_model=list[AlertEventOut], tags=["Alerts"])
def list_alert_events(
    session: SessionDep,
    acknowledged: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AlertEventOut]:
    stmt = select(AlertEvent).order_by(AlertEvent.id.desc()).limit(limit)
    if acknowledged is not None:
        stmt = stmt.where(AlertEvent.acknowledged.is_(acknowledged))
    return [_event_out(e) for e in session.scalars(stmt)]


@state_router.post(
    "/alerts/events/{event_id}/acknowledge", response_model=AlertEventOut, tags=["Alerts"]
)
def acknowledge_event(event_id: int, session: SessionDep) -> AlertEventOut:
    event = _get_or_404(session, AlertEvent, event_id, "Alert event")
    event.acknowledged = True
    session.commit()
    return _event_out(event)


__all__ = ["state_router", "get_session", "EPSILON"]
