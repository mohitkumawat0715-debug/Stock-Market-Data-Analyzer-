"""Finnhub `/quote` adapter (optional; requires a free API key in FINNHUB_API_KEY).

Documented behavior relied on (verify against https://finnhub.io/docs/api/quote):
    - GET https://finnhub.io/api/v1/quote?symbol=AAPL
    - The key is sent in the `X-Finnhub-Token` header so it never appears in URLs.
    - Response fields: c (current), d, dp, h, l, o, pc (previous close), t (UNIX seconds).
    - Unknown symbols return zeros, with t == 0.
    - Free plan: 60 calls/minute (HTTP 429 beyond that) and personal-use terms.
Finnhub does not guarantee real-time delivery on the free plan, so quotes are
always labeled as not real-time.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.exceptions import (
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    SymbolNotFoundError,
)
from app.providers.csv_provider import validate_ticker_symbol
from app.quotes.base import Quote

FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"


class FinnhubQuoteProvider:
    name = "finnhub"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(
                "FINNHUB_API_KEY is not set; quote polling is unavailable. "
                "Offline CSV analysis still works without it."
            )
        self._api_key = api_key
        self._client = client
        self._timeout = timeout_seconds

    def fetch_quote(self, ticker: str) -> Quote:
        symbol = validate_ticker_symbol(ticker)
        headers = {"X-Finnhub-Token": self._api_key}
        try:
            if self._client is not None:
                response = self._client.get(
                    FINNHUB_QUOTE_URL,
                    params={"symbol": symbol},
                    headers=headers,
                    timeout=self._timeout,
                )
            else:
                with httpx.Client() as client:
                    response = client.get(
                        FINNHUB_QUOTE_URL,
                        params={"symbol": symbol},
                        headers=headers,
                        timeout=self._timeout,
                    )
        except httpx.HTTPError as exc:
            # Only the exception type is reported; never echo request headers.
            raise ProviderUnavailableError(
                f"Finnhub request failed for '{symbol}': {type(exc).__name__}.",
                details={"ticker": symbol, "provider": self.name},
            ) from exc

        if response.status_code == 429:
            raise ProviderRateLimitError(
                "Finnhub rate limit exceeded; polling will back off.",
                details={"provider": self.name},
            )
        if response.status_code in (401, 403):
            raise ProviderUnavailableError(
                f"Finnhub rejected the request (HTTP {response.status_code}); check the API key "
                "and whether the symbol is included in your plan.",
                details={"ticker": symbol, "provider": self.name},
            )
        if response.status_code != 200:
            raise ProviderUnavailableError(
                f"Finnhub returned HTTP {response.status_code} for '{symbol}'.",
                details={"ticker": symbol, "provider": self.name},
            )

        try:
            payload = response.json()
            price = float(payload["c"])
            unix_ts = int(payload.get("t") or 0)
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderUnavailableError(
                f"Finnhub returned an unreadable payload for '{symbol}'.",
                details={"ticker": symbol, "provider": self.name},
            ) from exc

        if price <= 0.0 and unix_ts == 0:
            raise SymbolNotFoundError(
                f"Finnhub has no quote for '{symbol}'.",
                details={"ticker": symbol, "provider": self.name},
            )
        if price <= 0.0:
            raise ProviderUnavailableError(
                f"Finnhub returned a non-positive price for '{symbol}'.",
                details={"ticker": symbol, "provider": self.name},
            )

        def _opt(key: str) -> float | None:
            value = payload.get(key)
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            return number if number > 0.0 else None

        return Quote(
            ticker=symbol,
            price=price,
            provider=self.name,
            fetched_at=datetime.now(timezone.utc),
            exchange_timestamp=(
                datetime.fromtimestamp(unix_ts, tz=timezone.utc) if unix_ts > 0 else None
            ),
            open=_opt("o"),
            high=_opt("h"),
            low=_opt("l"),
            prev_close=_opt("pc"),
        )
