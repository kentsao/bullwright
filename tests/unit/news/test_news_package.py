"""bullwright-news unit tests: RSS parsing (fixture XML, no network),
dedupe hashing, fake sentiment, fixture EDGAR importance rules."""

from datetime import UTC, date, datetime

from bullwright_news import (
    IMPORTANT_FORMS,
    FakeSentimentAnalyzer,
    FilingRecord,
    FixtureEdgarClient,
    FixtureNewsProvider,
    NewsRecord,
)
from bullwright_news.providers import _parse_feed

RSS_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test Feed</title>
<item>
  <title>NVDA beats expectations as datacenter revenue surges</title>
  <link>https://example.com/a1</link>
  <description>Quarterly results came in well above consensus.</description>
  <pubDate>Mon, 13 Jul 2026 12:00:00 GMT</pubDate>
</item>
<item>
  <title>Analysts downgrade rival on weak guidance</title>
  <link>https://example.com/a2</link>
  <pubDate>Sun, 12 Jul 2026 09:30:00 GMT</pubDate>
</item>
<item><title></title></item>
</channel></rss>"""


def test_rss_parse_fixture() -> None:
    records = _parse_feed(RSS_FIXTURE, "NVDA", "test-feed")
    assert len(records) == 2  # empty-title item dropped
    first = records[0]
    assert first.ticker == "NVDA"
    assert "beats expectations" in first.title
    assert first.url == "https://example.com/a1"
    assert first.published_at == datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    assert first.summary and "consensus" in first.summary


def test_dedupe_hash_stable_and_distinct() -> None:
    a = NewsRecord("NVDA", datetime.now(UTC), "Same Title", None, "https://x/1", "s")
    b = NewsRecord("NVDA", datetime.now(UTC), "Same Title", None, "https://x/1", "s")
    c = NewsRecord("NVDA", datetime.now(UTC), "Same Title", None, "https://x/2", "s")
    assert a.content_hash == b.content_hash
    assert a.content_hash != c.content_hash


def test_fake_sentiment_directions() -> None:
    fake = FakeSentimentAnalyzer()
    up = fake.analyze("NVDA", "NVDA beats expectations with record growth")
    down = fake.analyze("NVDA", "NVDA misses estimates, analysts downgrade on weak outlook")
    neutral = fake.analyze("NVDA", "NVDA holds annual shareholder meeting")
    assert up.sentiment > 0 > down.sentiment
    assert neutral.sentiment == 0.0
    assert up.relevance > 0.5  # ticker mentioned


def test_fixture_edgar_and_importance() -> None:
    filings = {
        "NVDA": [
            FilingRecord("0001-24-000001", "NVDA", "8-K", date(2026, 7, 10), "Events", None),
            FilingRecord("0001-24-000002", "NVDA", "424B2", date(2026, 7, 9), "Prospectus", None),
        ]
    }
    client = FixtureEdgarClient(filings)
    got = client.recent_filings("NVDA")
    assert got[0].is_important is True  # 8-K
    assert got[1].is_important is False  # 424B2 not in the important set
    assert "10-K" in IMPORTANT_FORMS and "8-K" in IMPORTANT_FORMS
    assert client.recent_filings("ZZZZ") == []


def test_fixture_news_provider_filters_symbols() -> None:
    provider = FixtureNewsProvider()
    out = provider.fetch(["AAA", "BBB"])
    assert {r.ticker for r in out} == {"AAA", "BBB"}
    assert all(r.content_hash for r in out)
