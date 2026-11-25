"""Integration tests for FastAPI endpoints, interval consistency, error contracts, and CORS."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_yahoo_provider
from app.config import Settings
from app.exceptions import ProviderUnavailableError, SymbolNotFoundError
from app.main import create_app
from app.providers.base import MarketDataResult


class StubYahooProvider:
    """Offline stub for YahooFinanceProvider used in API endpoint tests."""

    def fetch_ohlcv(
        self,
        ticker: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        interval: str = "1d",
    ) -> MarketDataResult:
        if ticker.upper() == "DOWN":
            raise ProviderUnavailableError("Simulated Yahoo Finance outage.")
        raise SymbolNotFoundError(f"Symbol '{ticker}' not found in stub Yahoo provider.")


@pytest.fixture()
def client(temp_csv_dir: Path) -> TestClient:
    settings = Settings(
        app_name="Test Market Analyzer",
        environment="test",
        cors_origins=["http://localhost:3000"],
        sample_csv_dir=temp_csv_dir,
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_yahoo_provider] = lambda: StubYahooProvider()
    return TestClient(app)


def test_health_and_interactive_docs_endpoints(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert "DEMO" in payload["available_csv_tickers"]

    alias_resp = client.get("/health")
    assert alias_resp.status_code == 200

    docs_resp = client.get("/docs")
    assert docs_resp.status_code == 200
    assert "Swagger UI" in docs_resp.text


def test_market_data_indicators_and_backtest_success(client: TestClient) -> None:
    md_resp = client.get(
        "/api/v1/market-data/DEMO?source=csv&start_date=2025-01-10&end_date=2025-03-31"
    )
    assert md_resp.status_code == 200
    md = md_resp.json()
    assert md["metadata"]["source"] == "local_csv"
    assert md["metadata"]["is_realtime"] is False
    assert md["metadata"]["last_available_timestamp"] <= "2025-03-31"
    assert len(md["bars"]) == md["metadata"]["bar_count"]

    ind_resp = client.get("/api/v1/indicators/DEMO?source=csv&sma_fast=5&sma_slow=15")
    assert ind_resp.status_code == 200
    ind = ind_resp.json()
    assert ind["parameters"]["interval"] == "1d"
    assert ind["parameters"]["periods_per_year"] == 252
    # Warm-up bars serialize NaN cleanly as JSON null (None in Python) and use bar_return.
    assert "bar_return" in ind["bars"][0]
    assert "daily_return" not in ind["bars"][0]
    assert ind["bars"][0]["bar_return"] is None
    assert ind["bars"][1]["bar_return"] is not None
    assert ind["bars"][0]["sma_fast"] is None
    assert ind["bars"][0]["signal"] == "WARMUP"
    assert ind["bars"][-1]["sma_fast"] is not None
    assert ind["bars"][-1]["rsi"] is not None

    bt_resp = client.get(
        "/api/v1/backtest/DEMO?source=csv&sma_fast=5&sma_slow=15&transaction_cost_bps=12&risk_free_rate=0.02"
    )
    assert bt_resp.status_code == 200
    bt = bt_resp.json()
    assert bt["assumptions"]["interval"] == "1d"
    assert bt["assumptions"]["periods_per_year"] == 252
    assert bt["assumptions"]["execution_delay_bars"] == 1
    assert bt["assumptions"]["execution_fill_convention"] == "next_bar_close"
    assert bt["assumptions"]["transaction_cost_bps"] == 12.0
    assert bt["assumptions"]["risk_free_rate_annual"] == 0.02
    assert bt["assumptions"]["risk_free_rate_per_bar"] == pytest.approx(0.02 / 252.0, abs=1e-7)
    assert "sharpe_ratio" in bt["metrics"]
    assert len(bt["equity_curve"]) == 80
    assert "earning_position" in bt["equity_curve"][0]


@pytest.mark.parametrize(
    ("interval", "expected_periods"),
    [("1d", 252), ("1wk", 52), ("1mo", 12)],
)
def test_bundled_sample_csv_supports_1d_1wk_and_1mo_end_to_end(
    interval: str, expected_periods: int
) -> None:
    """Verify bundled AAPL.csv supports 1d, 1wk, and 1mo across market-data, indicators, and backtest."""
    default_client = TestClient(create_app())

    md_resp = default_client.get(f"/api/v1/market-data/AAPL?source=csv&interval={interval}")
    assert md_resp.status_code == 200
    md = md_resp.json()
    assert md["metadata"]["interval"] == interval

    ind_resp = default_client.get(
        f"/api/v1/indicators/AAPL?source=csv&interval={interval}&sma_fast=3&sma_slow=8&volatility_window=6"
    )
    assert ind_resp.status_code == 200
    ind = ind_resp.json()
    assert ind["metadata"]["interval"] == interval
    assert ind["parameters"]["interval"] == interval
    assert ind["parameters"]["periods_per_year"] == expected_periods
    assert "bar_return" in ind["bars"][-1]
    assert ind["bars"][-1]["rolling_volatility"] is not None

    bt_resp = default_client.get(
        f"/api/v1/backtest/AAPL?source=csv&interval={interval}&sma_fast=3&sma_slow=8&risk_free_rate=0.03"
    )
    assert bt_resp.status_code == 200
    bt = bt_resp.json()
    assert bt["metadata"]["interval"] == interval
    assert bt["assumptions"]["interval"] == interval
    assert bt["assumptions"]["periods_per_year"] == expected_periods
    assert bt["assumptions"]["risk_free_rate_per_bar"] == pytest.approx(
        0.03 / expected_periods, abs=1e-7
    )
    assert bt["metrics"]["max_drawdown"] <= 0.0


def test_api_error_handling_and_cors_headers(client: TestClient) -> None:
    # Invalid ticker characters -> 400
    assert client.get("/api/v1/market-data/BAD$TICKER?source=csv").status_code == 400
    # Reversed dates -> 400
    assert (
        client.get(
            "/api/v1/market-data/DEMO?source=csv&start_date=2025-05-01&end_date=2025-01-01"
        ).status_code
        == 400
    )
    # Invalid SMA relationship -> 400
    assert (
        client.get("/api/v1/indicators/DEMO?source=csv&sma_fast=30&sma_slow=10").status_code
        == 400
    )
    # Missing symbol -> 404
    assert client.get("/api/v1/market-data/UNKNOWN?source=csv").status_code == 404
    # Corrupt OHLC CSV -> 422
    bad_ohlc = client.get("/api/v1/market-data/BADOHLC?source=csv")
    assert bad_ohlc.status_code == 422
    assert bad_ohlc.json()["error_code"] == "DATA_VALIDATION_ERROR"
    # Upstream Yahoo failure -> 502
    assert client.get("/api/v1/market-data/DOWN?source=yahoo").status_code == 502
    # Malformed query parameter -> 422
    assert (
        client.get("/api/v1/market-data/DEMO?source=csv&start_date=invalid").status_code
        == 422
    )
    assert (
        client.get("/api/v1/backtest/DEMO?source=csv&interval=5m").status_code
        == 422
    )

    # Configured CORS origin allowed; unlisted origin omitted.
    ok_cors = client.get(
        "/api/v1/health", headers={"Origin": "http://localhost:3000"}
    )
    assert ok_cors.headers.get("access-control-allow-origin") == "http://localhost:3000"

    blocked_cors = client.get(
        "/api/v1/health", headers={"Origin": "https://untrusted.example.com"}
    )
    assert blocked_cors.headers.get("access-control-allow-origin") is None
