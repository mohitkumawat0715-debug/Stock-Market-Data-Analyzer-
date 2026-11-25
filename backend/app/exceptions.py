"""Domain exception hierarchy mapped to clear HTTP responses."""

from __future__ import annotations

from typing import Any


class AnalyzerError(Exception):
    """Base domain error carrying a machine-readable code and HTTP status."""

    status_code: int = 500
    error_code: str = "INTERNAL_ANALYZER_ERROR"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InvalidRequestError(AnalyzerError):
    """Raised when user-supplied parameters fail domain validation."""

    status_code = 400
    error_code = "INVALID_REQUEST"


class SymbolNotFoundError(AnalyzerError):
    """Raised when a requested ticker symbol does not exist in the provider."""

    status_code = 404
    error_code = "SYMBOL_NOT_FOUND"


class EmptyDatasetError(AnalyzerError):
    """Raised when a provider or date filter produces zero OHLCV bars."""

    status_code = 404
    error_code = "EMPTY_DATASET"


class DataValidationError(AnalyzerError):
    """Raised when ingested OHLCV records violate schema or integrity rules."""

    status_code = 422
    error_code = "DATA_VALIDATION_ERROR"


class ProviderUnavailableError(AnalyzerError):
    """Raised when an upstream market data provider fails or is unreachable."""

    status_code = 502
    error_code = "PROVIDER_ERROR"


class ResourceNotFoundError(AnalyzerError):
    """Raised when a stored resource (watchlist, portfolio, rule) does not exist."""

    status_code = 404
    error_code = "NOT_FOUND"


class ConflictError(AnalyzerError):
    """Raised when a request conflicts with existing stored state (for example duplicates)."""

    status_code = 409
    error_code = "CONFLICT"


class ProviderNotConfiguredError(AnalyzerError):
    """Raised when an optional provider needs credentials that are not set."""

    status_code = 503
    error_code = "PROVIDER_NOT_CONFIGURED"


class ProviderRateLimitError(ProviderUnavailableError):
    """Raised when a provider reports that its rate limit was exceeded."""

    error_code = "PROVIDER_RATE_LIMITED"
