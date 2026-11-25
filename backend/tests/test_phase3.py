"""Offline Phase 3 tests: persistence, portfolios, quotes, polling, and alerts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.config import Settings
from app.db import AlertRule, create_db_engine, run_migrations
from app.exceptions import (
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    SymbolNotFoundError,
)
from app.main import create_app
from app.quotes import FinnhubQuoteProvider, Quote, describe_freshness
from app.services import polling
from app.services.alerts import Observation, evaluate_alert_rules
from app.services.portfolio import compute_portfolio_state

NOW = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)


def _settings(tmp_path: Path, csv_dir: Path, **overrides) -> Settings:  # type: ignore[no-untyped-def]
    return Settings(
        environment="test",
        cors_origins=["http://localhost:3000"],
        sample_csv_dir=csv_dir,
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        finnhub_api_key="",
        quote_polling_enabled=False,
        **overrides,
    )


@pytest.fixture()
def app(tmp_path: Path, temp_csv_dir: Path):  # type: ignore[no-untyped-def]
    return create_app(_settings(tmp_path, temp_csv_dir))


@pytest.fixture()
def client(app):  # type: ignore[no-untyped-def]
    with TestClient(app) as test_client:  # context manager runs the lifespan (migrations)
        yield test_client


class StubQuoteProvider:
    name = "stub"

    def __init__(self, behavior: dict[str, object]) -> None:
        self.behavior = behavior

    def fetch_quote(self, ticker: str) -> Quote:
        outcome = self.behavior[ticker]
        if isinstance(outcome, Exception):
            raise outcome
        return Quote(
            ticker=ticker,
            price=float(outcome),  # type: ignore[arg-type]
            provider=self.name,
            fetched_at=datetime.now(timezone.utc),
            exchange_timestamp=datetime.now(timezone.utc) - timedelta(minutes=90),
        )


# ------------------------------------------------------------- persistence
def test_migration_creates_schema_and_data_survives_restart(
    tmp_path: Path, temp_csv_dir: Path
) -> None:
    settings = _settings(tmp_path, temp_csv_dir)
    run_migrations(settings.database_url)
    engine = create_db_engine(settings.database_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert {
        "watchlists", "watchlist_items", "portfolios", "paper_transactions",
        "quote_snapshots", "alert_rules", "alert_events", "alembic_version",
    } <= tables

    with TestClient(create_app(settings)) as first:
        assert first.post("/api/v1/watchlists", json={"name": "Core"}).status_code == 201
    with TestClient(create_app(settings)) as second:  # simulated restart, same database file
        names = [w["name"] for w in second.get("/api/v1/watchlists").json()]
    assert names == ["Core"]


# --------------------------------------------------------------- watchlists
def test_watchlist_crud_duplicates_and_validation(client: TestClient) -> None:
    wl = client.post("/api/v1/watchlists", json={"name": "Tech"}).json()
    assert client.post("/api/v1/watchlists", json={"name": "Tech"}).status_code == 409

    url = f"/api/v1/watchlists/{wl['id']}/items"
    added = client.post(url, json={"ticker": "demo", "note": "test"})
    assert added.status_code == 201
    assert added.json()["items"][0]["ticker"] == "DEMO"
    assert client.post(url, json={"ticker": "DEMO"}).status_code == 409
    assert client.post(url, json={"ticker": "BAD$"}).status_code == 400

    removed = client.delete(f"{url}/DEMO")
    assert removed.status_code == 200 and removed.json()["items"] == []
    assert client.delete(f"{url}/DEMO").status_code == 404

    assert client.delete(f"/api/v1/watchlists/{wl['id']}").status_code == 204
    assert client.post(url, json={"ticker": "DEMO"}).status_code == 404


# ---------------------------------------------------------------- portfolios
def test_average_cost_accounting_with_fees() -> None:
    class Tx:
        def __init__(self, side: str, qty: float, price: float, fee: float) -> None:
            self.ticker, self.side, self.quantity, self.price, self.fee = (
                "XYZ", side, qty, price, fee,
            )

    state = compute_portfolio_state(
        10_000.0, [Tx("BUY", 10, 100, 1), Tx("BUY", 10, 120, 1), Tx("SELL", 5, 130, 1)]
    )
    position = state.positions["XYZ"]
    assert position.quantity == 15
    assert position.cost_basis == pytest.approx(1651.5)
    assert state.realized_pnl == pytest.approx(98.5)
    assert state.cash == pytest.approx(10_000 - 1001 - 1201 + 649)


def test_portfolio_paper_trades_summary_and_rejections(client: TestClient) -> None:
    last_close = client.get("/api/v1/market-data/DEMO?source=csv").json()["bars"][-1]["close"]
    pid = client.post(
        "/api/v1/portfolios", json={"name": "Paper", "starting_cash": 10_000}
    ).json()["id"]
    assert client.post(
        "/api/v1/portfolios", json={"name": "Paper", "starting_cash": 5}
    ).status_code == 409

    base = f"/api/v1/portfolios/{pid}"
    buy = client.post(f"{base}/transactions", json={"ticker": "DEMO", "side": "BUY", "quantity": 10})
    assert buy.status_code == 201
    assert buy.json()["price"] == pytest.approx(last_close)
    assert buy.json()["price_source"] == "local_csv_last_close"

    summary = client.get(base).json()
    assert summary["valuation_complete"] is True
    assert summary["total_pnl"] == pytest.approx(0.0, abs=1e-6)
    assert summary["holdings"][0]["price_is_realtime"] is False

    sell = client.post(
        f"{base}/transactions",
        json={"ticker": "DEMO", "side": "SELL", "quantity": 4, "price": last_close + 5, "fee": 1},
    )
    assert sell.status_code == 201
    summary = client.get(base).json()
    assert summary["realized_pnl"] == pytest.approx(4 * 5 - 1)
    assert summary["holdings"][0]["quantity"] == pytest.approx(6)

    # Rejections: overselling, insufficient cash, unknown ticker without a supplied price.
    oversell = client.post(
        f"{base}/transactions", json={"ticker": "DEMO", "side": "SELL", "quantity": 99, "price": 1}
    )
    assert oversell.status_code == 400
    too_big = client.post(
        f"{base}/transactions",
        json={"ticker": "DEMO", "side": "BUY", "quantity": 1_000_000, "price": 100},
    )
    assert too_big.status_code == 400
    assert client.post(
        f"{base}/transactions", json={"ticker": "NOPE", "side": "BUY", "quantity": 1}
    ).status_code == 400
    assert len(client.get(f"{base}/transactions").json()) == 2  # rejected trades not stored

    # A held ticker with no available price makes the valuation explicitly incomplete.
    client.post(
        f"{base}/transactions", json={"ticker": "NOPE", "side": "BUY", "quantity": 1, "price": 10}
    )
    incomplete = client.get(base).json()
    assert incomplete["valuation_complete"] is False
    assert incomplete["total_value"] is None


# ------------------------------------------------------------ quote provider
def _finnhub(handler) -> FinnhubQuoteProvider:  # type: ignore[no-untyped-def]
    return FinnhubQuoteProvider("secret-key-123", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_finnhub_parses_quote_and_keeps_both_timestamps() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"], seen["url"] = request.headers, str(request.url)
        return httpx.Response(
            200, json={"c": 101.5, "o": 100.0, "h": 102.0, "l": 99.0, "pc": 98.0, "t": 1_767_625_200}
        )

    quote = _finnhub(handler).fetch_quote("aapl")
    assert quote.ticker == "AAPL" and quote.price == 101.5
    assert quote.exchange_timestamp == datetime.fromtimestamp(1_767_625_200, tz=timezone.utc)
    assert quote.fetched_at.tzinfo is not None
    assert seen["headers"]["x-finnhub-token"] == "secret-key-123"  # type: ignore[index]
    assert "secret-key-123" not in str(seen["url"])  # key travels in a header, not the URL


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(200, json={"c": 0, "t": 0}), SymbolNotFoundError),
        (httpx.Response(429), ProviderRateLimitError),
        (httpx.Response(401), ProviderUnavailableError),
        (httpx.Response(500), ProviderUnavailableError),
        (httpx.Response(200, text="not json"), ProviderUnavailableError),
    ],
)
def test_finnhub_failure_modes_never_leak_the_key(response: httpx.Response, expected: type) -> None:
    with pytest.raises(expected) as exc_info:
        _finnhub(lambda _request: response).fetch_quote("AAPL")
    assert "secret-key-123" not in str(exc_info.value.message)  # type: ignore[attr-defined]


def test_finnhub_network_error_and_missing_key() -> None:
    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(ProviderUnavailableError):
        _finnhub(boom).fetch_quote("AAPL")
    with pytest.raises(ProviderNotConfiguredError):
        FinnhubQuoteProvider("")


def test_freshness_never_claims_realtime() -> None:
    unknown = describe_freshness(None, NOW, recent_minutes=20)
    recent = describe_freshness(NOW - timedelta(minutes=5), NOW, recent_minutes=20)
    stale = describe_freshness(NOW - timedelta(hours=3), NOW, recent_minutes=20)
    assert (unknown.status, recent.status, stale.status) == ("unknown", "recent", "stale")
    assert not (unknown.is_realtime or recent.is_realtime or stale.is_realtime)


# ----------------------------------------------------- polling API (offline)
def test_polling_is_optional_and_offline_mode_still_works(client: TestClient) -> None:
    status = client.get("/api/v1/quotes/status").json()
    assert status["provider_configured"] is False and status["polling_active"] is False
    assert client.post("/api/v1/quotes/poll").json()["error_code"] == "PROVIDER_NOT_CONFIGURED"
    assert client.get("/api/v1/quotes/DEMO").status_code == 404
    assert client.get("/api/v1/market-data/DEMO?source=csv").status_code == 200


def test_poll_stores_quotes_labels_freshness_and_isolates_failures(
    app, client: TestClient  # type: ignore[no-untyped-def]
) -> None:
    wid = client.post("/api/v1/watchlists", json={"name": "W"}).json()["id"]
    for ticker in ("AAA", "BBB", "CCC"):
        client.post(f"/api/v1/watchlists/{wid}/items", json={"ticker": ticker})
    app.state.quote_provider = StubQuoteProvider(
        {"AAA": 10.0, "BBB": ProviderUnavailableError("down"), "CCC": 30.0}
    )

    result = client.post("/api/v1/quotes/poll").json()
    assert result["fetched"] == ["AAA", "CCC"]
    assert result["failed"] == {"BBB": "PROVIDER_ERROR"}  # one failure does not stop the rest

    quote = client.get("/api/v1/quotes/AAA").json()
    assert quote["price"] == 10.0
    assert quote["is_realtime"] is False
    assert quote["freshness_status"] == "stale"  # 90 minute old trade time vs 20 minute window
    assert quote["exchange_timestamp"] and quote["fetched_at"]
    assert client.get("/api/v1/quotes/BBB").status_code == 404

    status = client.get("/api/v1/quotes/status").json()
    assert status["provider_configured"] is True and status["last_failed"] == {"BBB": "PROVIDER_ERROR"}


def test_rate_limit_stops_the_cycle_and_cap_is_respected(
    app, client: TestClient  # type: ignore[no-untyped-def]
) -> None:
    wid = client.post("/api/v1/watchlists", json={"name": "W"}).json()["id"]
    for ticker in ("AAA", "BBB", "CCC"):
        client.post(f"/api/v1/watchlists/{wid}/items", json={"ticker": ticker})
    app.state.quote_provider = StubQuoteProvider(
        {"AAA": 1.0, "BBB": ProviderRateLimitError("slow down"), "CCC": 3.0}
    )
    result = client.post("/api/v1/quotes/poll").json()
    assert result["stopped_for_rate_limit"] is True
    assert result["fetched"] == ["AAA"] and "CCC" not in result["failed"]

    with app.state.session_factory() as session:
        capped = polling.poll_quotes_once(
            session, StubQuoteProvider({"AAA": 1.0, "BBB": 2.0, "CCC": 3.0}), max_symbols=1
        )
    assert capped.fetched == ["AAA"] and capped.skipped_over_cap == ["BBB", "CCC"]


def test_portfolio_prefers_polled_quote_over_csv(app, client: TestClient) -> None:  # type: ignore[no-untyped-def]
    pid = client.post("/api/v1/portfolios", json={"name": "P", "starting_cash": 1000}).json()["id"]
    client.post(f"/api/v1/portfolios/{pid}/transactions",
                json={"ticker": "AAA", "side": "BUY", "quantity": 1, "price": 10})
    app.state.quote_provider = StubQuoteProvider({"AAA": 25.0})
    client.post("/api/v1/quotes/poll")
    holding = client.get(f"/api/v1/portfolios/{pid}").json()["holdings"][0]
    assert holding["market_price"] == 25.0
    assert holding["price_source"] == "quote:stub"
    assert holding["price_is_realtime"] is False


def test_polling_loop_backs_off_exponentially_and_survives_crashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[int] = []

    async def fake_sleep(seconds: int) -> None:
        delays.append(seconds)
        if len(delays) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(polling.asyncio, "sleep", fake_sleep)

    def crash() -> polling.PollResult:
        raise RuntimeError("boom")

    status = polling.PollStatus()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(polling.run_polling_loop(crash, status, interval_seconds=30))
    assert delays == [60, 120, 240]
    assert status.consecutive_failures == 3


# -------------------------------------------------------------------- alerts
def test_alert_rule_validation(client: TestClient) -> None:
    post = lambda body: client.post("/api/v1/alerts/rules", json=body)  # noqa: E731
    assert post({"ticker": "DEMO", "kind": "price_above"}).status_code == 400
    assert post({"ticker": "DEMO", "kind": "rsi_above", "threshold": 150}).status_code == 400
    assert post({"ticker": "DEMO", "kind": "sma_crossover_buy", "threshold": 1}).status_code == 400
    assert post({"ticker": "DEMO", "kind": "bogus", "threshold": 1}).status_code == 422
    assert post({"ticker": "DEMO", "kind": "price_above", "threshold": 1}).status_code == 201


def test_alert_evaluation_persists_events_without_duplicates(client: TestClient) -> None:
    rule = client.post(
        "/api/v1/alerts/rules", json={"ticker": "DEMO", "kind": "price_above", "threshold": 1.0}
    ).json()
    rsi_rule = client.post(
        "/api/v1/alerts/rules",
        json={"ticker": "DEMO", "kind": "rsi_below", "threshold": 100, "cooldown_minutes": 0},
    ).json()
    never = client.post(
        "/api/v1/alerts/rules", json={"ticker": "DEMO", "kind": "price_below", "threshold": 0.01}
    ).json()

    first = client.post("/api/v1/alerts/evaluate").json()
    assert first["evaluated"] == 3 and first["triggered"] == 2

    second = client.post("/api/v1/alerts/evaluate").json()
    assert second["triggered"] == 0  # condition is still true: no duplicate event

    events = client.get("/api/v1/alerts/events").json()
    assert {e["rule_id"] for e in events} == {rule["id"], rsi_rule["id"]}
    assert never["id"] not in {e["rule_id"] for e in events}
    price_event = next(e for e in events if e["rule_id"] == rule["id"])
    assert price_event["observation_source"] == "local_csv_last_close"
    assert "not advice" in price_event["message"]

    ack = client.post(f"/api/v1/alerts/events/{price_event['id']}/acknowledge").json()
    assert ack["acknowledged"] is True
    unread = client.get("/api/v1/alerts/events?acknowledged=false").json()
    assert price_event["id"] not in {e["id"] for e in unread}

    patched = client.patch(f"/api/v1/alerts/rules/{rule['id']}", json={"active": False}).json()
    assert patched["active"] is False and patched["condition_met"] is False
    assert client.delete(f"/api/v1/alerts/rules/{rule['id']}").status_code == 204
    assert client.delete(f"/api/v1/alerts/rules/{rule['id']}").status_code == 404


class ScriptedObserver:
    """Returns queued observations or raises queued errors, one per rule evaluation."""

    def __init__(self, script: list[object]) -> None:
        self.script = script

    def observe(self, _rule: AlertRule) -> Observation:
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item  # type: ignore[return-value]


def test_edge_detection_cooldown_suppression_and_provider_failure(app) -> None:  # type: ignore[no-untyped-def]
    def obs(price: float) -> Observation:
        return Observation(price=price, source="test", as_of="t")

    with app.state.session_factory() as session:
        run_migrations(app.state.settings.database_url)
        rule = AlertRule(ticker="AAA", kind="price_above", threshold=100.0, cooldown_minutes=60)
        session.add(rule)
        session.commit()

        def run(observation: object, minutes: int):  # type: ignore[no-untyped-def]
            return evaluate_alert_rules(
                session, ScriptedObserver([observation]), now=NOW + timedelta(minutes=minutes)
            )

        assert run(obs(101), 0).triggered == 1               # false -> true fires
        assert run(obs(105), 5).triggered == 0               # still true: no duplicate
        assert run(obs(99), 10).triggered == 0               # condition clears
        suppressed = run(obs(101), 20)                       # re-fires inside cooldown
        assert (suppressed.triggered, suppressed.suppressed_by_cooldown) == (0, 1)

        failed = run(ProviderUnavailableError("down"), 30)   # provider failure
        assert failed.errors[0]["error_code"] == "PROVIDER_ERROR" and failed.evaluated == 0

        after = run(obs(101), 61)                            # cooldown over, still true: fires
        assert after.triggered == 1
        session.refresh(rule)
        assert rule.condition_met is True and len(rule.events) == 2
