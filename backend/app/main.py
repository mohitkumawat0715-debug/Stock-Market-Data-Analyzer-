"""FastAPI application entrypoint, CORS setup, lifespan (migrations and polling), and errors."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import health_check, router
from app.api.state_routes import state_router
from app.config import Settings, get_settings
from app.db import create_db_engine, create_session_factory, run_migrations
from app.exceptions import AnalyzerError
from app.providers import CSVMarketDataProvider, YahooFinanceProvider
from app.quotes import FinnhubQuoteProvider
from app.schemas import EDUCATIONAL_DISCLAIMER
from app.services.alerts import MarketObserver
from app.services.polling import PollStatus, build_cycle, run_polling_loop


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    active_settings = settings or get_settings()

    engine = create_db_engine(active_settings.database_url)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Migrations run at startup so first-time local setup needs no extra command.
        run_migrations(active_settings.database_url)
        task: asyncio.Task[None] | None = None
        provider = app.state.quote_provider
        if active_settings.quote_polling_enabled and provider is not None:
            csv_provider = CSVMarketDataProvider(active_settings.sample_csv_dir)
            yahoo_provider = YahooFinanceProvider()
            cycle = build_cycle(
                session_factory,
                provider,
                lambda session: MarketObserver(
                    session,
                    csv_provider,
                    lambda src: csv_provider if src == "csv" else yahoo_provider,
                ),
                max_symbols=active_settings.quote_max_symbols_per_cycle,
            )
            task = asyncio.create_task(
                run_polling_loop(
                    cycle,
                    app.state.poll_status,
                    interval_seconds=active_settings.quote_poll_interval_seconds,
                )
            )
            app.state.polling_task = task
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                app.state.polling_task = None
            engine.dispose()

    application = FastAPI(
        title=active_settings.app_name,
        version=active_settings.app_version,
        description=(
            "Modular market analysis backend providing normalized historical OHLCV data, "
            "technical indicators (SMA, EMA, RSI, MACD, rolling volatility), educational "
            "crossover signals, look-ahead-safe backtesting, persistent watchlists, simulated "
            "paper portfolios, optional quote polling, and alerts.\n\n"
            f"Disclaimer: {EDUCATIONAL_DISCLAIMER}"
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    application.state.settings = active_settings
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.poll_status = PollStatus()
    application.state.polling_task = None
    # The quote provider exists only when a key is configured (offline otherwise).
    application.state.quote_provider = (
        FinnhubQuoteProvider(active_settings.finnhub_api_key)
        if active_settings.finnhub_api_key
        else None
    )
    if settings is not None:
        application.dependency_overrides[get_settings] = lambda: active_settings

    # Configure explicit CORS origins for local Next.js dashboard integration
    # rather than permissive wildcard defaults.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type"],
    )

    @application.exception_handler(AnalyzerError)
    async def handle_analyzer_error(
        _request: Request, exc: AnalyzerError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
            },
        )

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        sanitized_errors = [
            {
                "loc": [str(part) for part in err.get("loc", ())],
                "msg": err.get("msg", "Invalid parameter."),
                "type": err.get("type", "validation_error"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error_code": "REQUEST_VALIDATION_ERROR",
                "message": "One or more request parameters failed validation.",
                "details": {"errors": sanitized_errors},
            },
        )

    application.include_router(router, prefix="/api/v1")
    application.include_router(state_router, prefix="/api/v1")

    # Root-level convenience health route alongside /api/v1/health.
    application.add_api_route(
        "/health",
        health_check,
        methods=["GET"],
        tags=["System"],
        summary="Root health check alias",
    )

    return application


app = create_app()
