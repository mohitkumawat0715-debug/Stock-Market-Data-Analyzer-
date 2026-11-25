"""Quote polling cycle and optional background scheduler."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AlertRule, PaperTransaction, QuoteSnapshot, WatchlistItem
from app.exceptions import AnalyzerError, ProviderRateLimitError
from app.quotes.base import QuoteProvider

logger = logging.getLogger("stock_analyzer.polling")


@dataclass
class PollResult:
    fetched: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)  # ticker -> error code
    skipped_over_cap: list[str] = field(default_factory=list)
    stopped_for_rate_limit: bool = False
    finished_at: datetime | None = None


@dataclass
class PollStatus:
    """Last background cycle outcome, exposed by GET /quotes/status."""

    last_result: PollResult | None = None
    consecutive_failures: int = 0
    next_delay_seconds: int | None = None


def tracked_tickers(session: Session) -> list[str]:
    """Distinct tickers from watchlists, active alert rules, and paper transactions."""
    tickers: set[str] = set()
    tickers.update(session.scalars(select(WatchlistItem.ticker)).all())
    tickers.update(
        session.scalars(select(AlertRule.ticker).where(AlertRule.active.is_(True))).all()
    )
    tickers.update(session.scalars(select(PaperTransaction.ticker)).all())
    return sorted(tickers)


def poll_quotes_once(
    session: Session, provider: QuoteProvider, *, max_symbols: int
) -> PollResult:
    """Fetch and store one quote per tracked ticker (capped to respect rate limits).

    A failure on one symbol never aborts the others, except a rate-limit response,
    which stops the cycle immediately so the caller can back off.
    """
    result = PollResult()
    tickers = tracked_tickers(session)
    result.skipped_over_cap = tickers[max_symbols:]
    for ticker in tickers[:max_symbols]:
        try:
            quote = provider.fetch_quote(ticker)
        except ProviderRateLimitError:
            result.failed[ticker] = "PROVIDER_RATE_LIMITED"
            result.stopped_for_rate_limit = True
            break
        except AnalyzerError as exc:
            result.failed[ticker] = exc.error_code
            continue
        session.add(
            QuoteSnapshot(
                ticker=quote.ticker,
                price=quote.price,
                open=quote.open,
                high=quote.high,
                low=quote.low,
                prev_close=quote.prev_close,
                provider=quote.provider,
                exchange_timestamp=quote.exchange_timestamp,
                fetched_at=quote.fetched_at,
            )
        )
        result.fetched.append(ticker)
    session.commit()
    result.finished_at = datetime.now(timezone.utc)
    return result


async def run_polling_loop(
    run_cycle: Callable[[], PollResult],
    status: PollStatus,
    *,
    interval_seconds: int,
    max_backoff_seconds: int = 900,
) -> None:
    """Run `run_cycle` forever in a worker thread with exponential backoff on failure."""
    delay = interval_seconds
    while True:
        try:
            result = await asyncio.to_thread(run_cycle)
            status.last_result = result
            if result.stopped_for_rate_limit or (result.failed and not result.fetched):
                status.consecutive_failures += 1
                delay = min(max_backoff_seconds, interval_seconds * 2**status.consecutive_failures)
            else:
                status.consecutive_failures = 0
                delay = interval_seconds
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the loop must survive any cycle error
            logger.exception("Quote polling cycle crashed; backing off.")
            status.consecutive_failures += 1
            delay = min(max_backoff_seconds, interval_seconds * 2**status.consecutive_failures)
        status.next_delay_seconds = delay
        await asyncio.sleep(delay)


def build_cycle(
    session_factory: sessionmaker[Session],
    provider: QuoteProvider,
    observer_factory: Callable[[Session], object],
    *,
    max_symbols: int,
) -> Callable[[], PollResult]:
    """Create the function the scheduler runs: poll quotes, then evaluate alerts."""
    from app.services.alerts import evaluate_alert_rules

    def _cycle() -> PollResult:
        with session_factory() as session:
            result = poll_quotes_once(session, provider, max_symbols=max_symbols)
            evaluate_alert_rules(session, observer_factory(session))  # type: ignore[arg-type]
            return result

    return _cycle
