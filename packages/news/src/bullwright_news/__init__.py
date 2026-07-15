"""Bullwright news signals (ADR-0002)."""

from bullwright_news.edgar import (
    IMPORTANT_FORMS,
    EdgarClient,
    FilingRecord,
    FixtureEdgarClient,
)
from bullwright_news.providers import (
    FixtureNewsProvider,
    NewsProvider,
    NewsRecord,
    RSSNewsProvider,
    get_news_provider,
)
from bullwright_news.sentiment import (
    FakeSentimentAnalyzer,
    OllamaSentimentAnalyzer,
    SentimentAnalyzer,
    SentimentResult,
)

__all__ = [
    "IMPORTANT_FORMS",
    "EdgarClient",
    "FakeSentimentAnalyzer",
    "FilingRecord",
    "FixtureEdgarClient",
    "FixtureNewsProvider",
    "NewsProvider",
    "NewsRecord",
    "OllamaSentimentAnalyzer",
    "RSSNewsProvider",
    "SentimentAnalyzer",
    "SentimentResult",
    "get_news_provider",
]
