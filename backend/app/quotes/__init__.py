"""Optional quote providers with explicit timestamp and freshness labeling."""

from app.quotes.base import (
    FreshnessInfo,
    Quote,
    QuoteProvider,
    describe_freshness,
)
from app.quotes.finnhub import FinnhubQuoteProvider

__all__ = [
    "FinnhubQuoteProvider",
    "FreshnessInfo",
    "Quote",
    "QuoteProvider",
    "describe_freshness",
]
