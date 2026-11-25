"""Environment-driven application configuration.

Loads non-secret runtime settings from environment variables (and an optional
local .env file when present). No paid API keys or credentials are required.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Resolve key project directories relative to this file so running from either
# the repository root or backend/ resolves paths predictably on Windows.
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT_DIR = BACKEND_DIR.parent
DEFAULT_SAMPLE_CSV_DIR = BACKEND_DIR / "data" / "sample"

# Load local .env if present without overriding explicit process env vars.
load_dotenv(REPO_ROOT_DIR / ".env", override=False)
load_dotenv(BACKEND_DIR / ".env", override=False)


def _parse_cors_origins(raw_value: str) -> list[str]:
    """Split a comma-separated CORS origin string into clean URL origins."""
    origins = [item.strip() for item in raw_value.split(",") if item.strip()]
    if not origins:
        return ["http://localhost:3000", "http://127.0.0.1:3000"]
    return origins


@dataclass(frozen=True)
class Settings:
    """Immutable configuration container for the FastAPI application."""

    app_name: str = field(
        default_factory=lambda: os.getenv(
            "STOCK_ANALYZER_APP_NAME", "Stock Market Data Analyzer API"
        )
    )
    app_version: str = "0.1.0"
    environment: str = field(
        default_factory=lambda: os.getenv("STOCK_ANALYZER_ENV", "development")
    )
    host: str = field(
        default_factory=lambda: os.getenv("STOCK_ANALYZER_HOST", "127.0.0.1")
    )
    port: int = field(
        default_factory=lambda: int(os.getenv("STOCK_ANALYZER_PORT", "8000"))
    )
    cors_origins: list[str] = field(
        default_factory=lambda: _parse_cors_origins(
            os.getenv(
                "STOCK_ANALYZER_CORS_ORIGINS",
                "http://localhost:3000,http://127.0.0.1:3000",
            )
        )
    )
    sample_csv_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("STOCK_ANALYZER_CSV_DIR", str(DEFAULT_SAMPLE_CSV_DIR))
        ).resolve()
    )
    default_risk_free_rate: float = field(
        default_factory=lambda: float(
            os.getenv("STOCK_ANALYZER_DEFAULT_RISK_FREE_RATE", "0.02")
        )
    )
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "STOCK_ANALYZER_DATABASE_URL",
            f"sqlite:///{(BACKEND_DIR / 'data' / 'stock_analyzer.db').as_posix()}",
        )
    )
    # Optional quote-polling credentials. Keep the key out of repr() and logs.
    finnhub_api_key: str = field(
        default_factory=lambda: os.getenv("FINNHUB_API_KEY", "").strip(), repr=False
    )
    quote_polling_enabled: bool = field(
        default_factory=lambda: os.getenv("STOCK_ANALYZER_QUOTE_POLLING_ENABLED", "false")
        .strip()
        .lower()
        in ("1", "true", "yes")
    )
    quote_poll_interval_seconds: int = field(
        default_factory=lambda: max(
            30, int(os.getenv("STOCK_ANALYZER_QUOTE_POLL_INTERVAL_SECONDS", "120"))
        )
    )
    quote_max_symbols_per_cycle: int = field(
        default_factory=lambda: max(
            1, int(os.getenv("STOCK_ANALYZER_QUOTE_MAX_SYMBOLS_PER_CYCLE", "20"))
        )
    )
    quote_recent_minutes: int = field(
        default_factory=lambda: int(os.getenv("STOCK_ANALYZER_QUOTE_RECENT_MINUTES", "20"))
    )
    default_transaction_cost_bps: float = field(
        default_factory=lambda: float(
            os.getenv("STOCK_ANALYZER_DEFAULT_TRANSACTION_COST_BPS", "10.0")
        )
    )


def get_settings() -> Settings:
    """Return a fresh Settings instance reflecting current environment state."""
    return Settings()
