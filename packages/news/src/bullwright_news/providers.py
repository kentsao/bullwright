"""News enters through a protocol, never a scraper (ADR-0002 §1).

RSSNewsProvider covers Yahoo Finance per-ticker feeds and Google News
per-ticker queries — broad, free, and stable. FixtureNewsProvider keeps
CI and fresh clones fully offline. Paid APIs plug in behind the same
protocol later.
"""

import calendar
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import feedparser  # type: ignore[import-untyped]
import httpx2 as httpx

USER_AGENT = "Bullwright/0.5 (research framework; local-first)"
MAX_ITEMS_PER_FEED = 25


@dataclass(frozen=True)
class NewsRecord:
    ticker: str
    published_at: datetime
    title: str
    summary: str | None
    url: str | None
    source: str

    @property
    def content_hash(self) -> str:
        basis = (self.url or "") + "|" + self.title.strip().lower()
        return "sha256:" + hashlib.sha256(basis.encode()).hexdigest()[:32]


class NewsProvider(Protocol):
    name: str

    def fetch(self, symbols: list[str]) -> list[NewsRecord]: ...


def _parse_feed(raw: bytes, symbol: str, source: str) -> list[NewsRecord]:
    parsed = feedparser.parse(raw)
    records: list[NewsRecord] = []
    for entry in parsed.entries[:MAX_ITEMS_PER_FEED]:
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        struct = entry.get("published_parsed") or entry.get("updated_parsed")
        published = (
            # feedparser normalizes *_parsed to UTC; timegm reads it as UTC
            # (mktime would wrongly apply the local timezone)
            datetime.fromtimestamp(calendar.timegm(struct), tz=UTC) if struct else datetime.now(UTC)
        )
        summary = (entry.get("summary") or "").strip() or None
        if summary and len(summary) > 2000:
            summary = summary[:2000]
        records.append(
            NewsRecord(
                ticker=symbol,
                published_at=published,
                title=title[:490],
                summary=summary,
                url=(entry.get("link") or None),
                source=source,
            )
        )
    return records


class RSSNewsProvider:
    """Yahoo Finance + Google News RSS per ticker. Failures on one feed
    never abort the crawl — partial data beats no data."""

    name = "rss"

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    def _feeds(self, symbol: str) -> list[tuple[str, str]]:
        return [
            (
                f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US",
                "yahoo-finance",
            ),
            (
                f"https://news.google.com/rss/search?q={symbol}+stock&hl=en-US&gl=US&ceid=US:en",
                "google-news",
            ),
        ]

    def fetch(self, symbols: list[str]) -> list[NewsRecord]:
        records: list[NewsRecord] = []
        with httpx.Client(
            timeout=self.timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            for symbol in symbols:
                for url, source in self._feeds(symbol):
                    try:
                        resp = client.get(url)
                        resp.raise_for_status()
                    except httpx.HTTPError:
                        continue  # skip broken feed, keep crawling
                    records.extend(_parse_feed(resp.content, symbol, source))
        return records


class FixtureNewsProvider:
    """Deterministic synthetic headlines for tests/CI/template users."""

    name = "fixture"

    def __init__(self, items: list[NewsRecord] | None = None) -> None:
        self._items = items

    def fetch(self, symbols: list[str]) -> list[NewsRecord]:
        if self._items is not None:
            return [r for r in self._items if r.ticker in symbols]
        now = datetime.now(UTC)
        out = []
        for symbol in symbols:
            seed = int.from_bytes(hashlib.sha256(symbol.encode()).digest()[:2], "big")
            tone = ["beats expectations", "misses estimates", "announces expansion"][seed % 3]
            out.append(
                NewsRecord(
                    ticker=symbol,
                    published_at=now,
                    title=f"{symbol} {tone} in fixture universe",
                    summary=f"Synthetic item for {symbol}.",
                    url=None,
                    source="fixture",
                )
            )
        return out


def get_news_provider(name: str, **kwargs: Any) -> NewsProvider:
    if name == "rss":
        return RSSNewsProvider(**kwargs)
    if name == "fixture":
        return FixtureNewsProvider()
    raise KeyError(f"unknown news provider {name!r} (have: rss, fixture)")
