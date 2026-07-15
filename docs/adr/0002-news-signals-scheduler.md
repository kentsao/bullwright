# ADR-0002: News signals, SEC filings, sentiment index, scheduler

**Date:** 2026-07-15 · **Status:** accepted · **Decider:** operator (feature request), design by build agent

## Context
Operator wants: automated news collection ("web crawler / search API"),
SEC filing monitoring, a more precise per-stock score using news
sentiment analyzed by local/cloud models, and a scheduler settable by
agents or manually, plus alerts.

## Decisions

1. **Providers, not a crawler.** Scraping arbitrary websites is fragile
   (selector rot), legally murky (ToS/robots), and unmaintainable in a
   public template. News enters through a `NewsProvider` protocol:
   - `rss` adapter (default real source): Yahoo Finance per-ticker feeds
     + Google News per-ticker query feeds — broad coverage, free, stable.
   - `fixture` adapter: deterministic synthetic items for CI/template use.
   - Paid APIs (NewsAPI, Finnhub, Polygon, …) are future adapters behind
     the same protocol. Same pattern as MarketDataProvider (ADR-0001 era).

2. **SEC via official APIs only.** `data.sec.gov` submissions JSON per
   CIK (ticker→CIK from the official company_tickers.json), descriptive
   User-Agent as SEC requires, important form types (10-K, 10-Q, 8-K,
   S-1, 4, 13D/G, DEF 14A) stored as `filings` rows; new important
   filings raise alerts. Full-text/XBRL fundamentals: future adapter
   (would also fix the value/quality fundamentals-history gap).

3. **Sentiment is model-analyzed, provider-agnostic.** A
   `SentimentAnalyzer` protocol scores each stored news item
   (sentiment −1..1, relevance 0..1) via structured output. Default:
   local Ollama model (BW_LOCAL_MODEL); `FakeSentimentAnalyzer`
   (keyword-based, deterministic) for CI. Cloud models can be plugged in
   later behind the same protocol.

4. **`news_sentiment` becomes a sixth index** — relevance- and
   recency-weighted (10-day half-life) mean of analyzed item sentiment;
   None when no analyzed news (missing-weight redistribution handles it).
   The existing `sentiment` index (agent report verdicts) is renamed
   conceptually to "analyst sentiment" in docs; keys stay stable. New
   default-v2 weight profile includes both; the old `default` remains
   locked for reproducibility of past backtests.

5. **Scheduler lives in the worker.** A `schedules` table (interval
   minutes + next_run_at) is ticked by the worker loop; due schedules
   enqueue normal jobs, idempotent per (schedule, due slot). No cron
   daemon, no new process. Operator manages via `bw schedules` / API;
   agents may create/pause schedules only for whitelisted job kinds
   (news_crawl, sec_sync, sentiment_analyze, alert_scan) under a new
   `schedules:write` scope — never arbitrary kinds.

6. **Alerts are rows, not pushes.** `alert_scan` evaluates rules (new
   important filing, 24h sentiment spike, composite rank jump) into an
   `alerts` table shown on the ops dashboard and `GET /v1/alerts`.
   Push channels (email/webhook) are a future adapter on top.

## Consequences
- CI never touches the network: RSS/EDGAR/sentiment all have fixtures.
- The index registry proves its protocol: sixth index lands with zero
  scoring-engine changes.
- data/ hygiene unchanged: fetched news/filings stay in the DB, which is
  local; nothing fetched is committed.
