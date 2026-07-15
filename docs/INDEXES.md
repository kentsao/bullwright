# Bullwright — Quant Index Protocol, Weighting & Backtesting

**Version:** 0.1-draft · **Status:** awaiting review

## 1. Concepts

An **index** turns raw data for one ticker on one date into a `raw_value`,
which is then **normalized cross-sectionally** (across the watchlist, same
date) to a 0–100 `score`. A **weight profile** combines index scores into a
single **composite score** (also 0–100) and a rank. A **backtest** replays
composite-score-driven portfolio selection over history.

Normalization (v1): winsorize raw values at p5/p95 across the universe,
then min-max to 0–100, flipping when `direction = lower_better`. Rationale:
robust to outliers, dead simple to explain on the methodology blog page.
(Z-score percentile is the specced alternative — see OPEN_DECISIONS D4.)

## 2. Core indexes (v1)

All computable from free daily bars + yfinance fundamentals. Each has a
methodology section auto-rendered on the blog from `index_definitions`.

| key | direction | raw_value (v1 formula) |
|---|---|---|
| `value` | lower_better | blended rank of P/E (ttm), EV/EBITDA, P/S; missing components dropped with reweight |
| `momentum` | higher_better | 126-day return skipping most recent 21 days (12-1 style, halved for our horizon) |
| `quality` | higher_better | blended rank of ROE, gross margin, debt/equity (inverted) |
| `volatility` | lower_better | 63-day annualized std of daily log returns |
| `sentiment` | higher_better | confidence-weighted mean of published report verdict ratings (analyst sentiment), 90-day half-life decay; neutral 50 when no coverage |
| `news_sentiment` | higher_better | relevance x recency-weighted mean of model-analyzed news item sentiment, 10-day half-life; missing when no analyzed news (ADR-0002) |

`sentiment` is the loop-closer: agent research feeds the quant layer.

## 3. The index protocol (adding a new index)

An index is a Python class in `packages/core/indexes/`:

```python
class Index(Protocol):
    key: str                 # unique, snake_case
    version: str             # bump when the formula changes
    direction: Direction     # HIGHER_BETTER | LOWER_BETTER
    requires: set[str]       # {'price_bars'} | {'fundamentals'} | {'reports'}
    min_history_days: int

    def compute(self, ctx: IndexContext) -> float | None:
        """raw_value for one (ticker, date); None = insufficient data.
        ctx provides ONLY point-in-time data: bars/fundamentals/reports
        with as_of <= date. Look-ahead is structurally impossible —
        IndexContext simply has no API for future data."""
```

Registration: add the class to `INDEX_REGISTRY`, run `bw indexes sync`
(upserts `index_definitions`), backfill via worker job. Contract tests in
`tests/unit/indexes/` run every registered index through: determinism
(same inputs → same output), None-on-short-history, no-NaN, and a
look-ahead canary (poisoned future data must not change output).

Rules: an index never reads the DB directly (only `IndexContext`), never
does I/O, is pure and vectorizable. `version` bump forces recompute of its
history.

## 4. Weight profiles (adjustable weights)

```json
{
  "name": "default",
  "weights": {"value": 0.20, "momentum": 0.25, "quality": 0.25,
              "volatility": 0.10, "sentiment": 0.20}
}
```

- Weights must be ≥ 0 and sum to 1.0 (±1e-9); API rejects otherwise.
- Omitted index = weight 0. Unknown key = 422.
- If an index score is missing for a ticker/date, its weight is
  redistributed pro-rata across present indexes; if >50% of total weight
  is missing, composite is null for that ticker/date (shown as "insufficient
  data", never a fake 50).
- Profiles are immutable once a backtest references them (edit = new
  profile version) — keeps backtests reproducible.
- Operator edits via `bw weights set` or `POST /weight-profiles` (admin).

## 5. Backtest spec (3–6 months, daily bars)

**Strategy (v1, deliberately simple):** on each rebalance date (weekly,
Monday close), rank universe by composite score for that date; hold top N
(default 5) equal-weighted; apply transaction cost `cost_bps` (default 10)
on turnover. Benchmark: equal-weighted universe and SPY.

**Config** (`POST /backtests`):
```json
{"weight_profile_id": "wp_...", "from": "2026-01-05", "to": "2026-07-03",
 "universe": ["watchlist"], "rebalance": "weekly",
 "config": {"top_n": 5, "cost_bps": 10, "benchmark": "SPY"}}
```

**Outputs** (stored in `backtest_runs.metrics` + artifact dir):
total return, CAGR (annualized, with a small-sample caveat flag when
window < 1y), Sharpe (rf=0), max drawdown, hit rate vs benchmark,
turnover, equity curve CSV, per-rebalance holdings log.

**Integrity rules (testable):**
- B1 point-in-time only: scores used at rebalance t computed from data ≤ t.
- B2 reproducible: `(snapshot_id, code_version, profile_id, config)` fully
  determines output; CI re-runs a fixture backtest and diffs bit-for-bit.
- B3 survivorship: universe = watchlist membership *as of* each date
  (membership changes are dated in `tickers.meta`).
- B4 honesty: metrics JSON always includes `benchmark_return` next to
  `total_return`; the blog page never shows one without the other.
- B5 small-sample humility: every backtest < 12 months renders with a
  banner: "3–6 month backtests are weather, not climate."

**Non-goals v1:** intraday, shorting, position sizing beyond equal-weight,
optimization/auto-tuning of weights (fun later; overfitting machine now).

## 6. Weight tuning UX (fast-follow, specced)

`bw weights sweep --grid value=0..0.4:0.1,momentum=...` runs a grid of
profiles through the same backtest window and emits a comparison table.
Guardrail: output is sorted by *out-of-window* performance on a holdout
month to make overfitting visible.
