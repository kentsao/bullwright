# Bullwright — Database Schema

**Version:** 0.1-draft · SQLite (dev) / Postgres 16 (cloud) via SQLAlchemy 2 + Alembic.

Types shown as Postgres; SQLite maps naturally (JSONB→TEXT+json1,
TIMESTAMPTZ→TEXT ISO8601). All PKs are ULID strings. All tables carry
`created_at`, `updated_at`.

## 1. Entity overview

```
agents ──< api_keys
agents ──< agent_runs ──< audit_events
tickers ──< reports ──< report_chunks (vector)
tickers ──< price_bars
tickers ──< index_scores >── indexes(registry, code-defined)
weight_profiles ──< composite_scores
weight_profiles ──< backtest_runs
subscribers ──< subscriptions ──< entitlements     (phase 4, flagged)
jobs (worker queue)
```

## 2. Tables

### agents / api_keys
```sql
agents (
  agent_id      TEXT PRIMARY KEY,            -- agt_...
  name          TEXT UNIQUE NOT NULL,        -- 'claude', 'gemini', 'gemma-local'
  kind          TEXT NOT NULL,               -- 'cloud' | 'local' | 'human'
  default_model TEXT,                        -- 'claude-fable-5', 'gemini-2.5-pro', 'gemma4:12b-mlx'
  is_active     BOOLEAN NOT NULL DEFAULT true
);
api_keys (
  key_id      TEXT PRIMARY KEY,
  agent_id    TEXT NOT NULL REFERENCES agents,
  key_prefix  TEXT NOT NULL,                 -- 'bw_live_ab12' for display
  key_hash    TEXT NOT NULL,                 -- argon2id
  scopes      TEXT[] NOT NULL,
  expires_at  TIMESTAMPTZ,
  revoked_at  TIMESTAMPTZ
);
```

### tickers / price_bars
```sql
tickers (
  ticker_id  TEXT PRIMARY KEY,
  symbol     TEXT NOT NULL, exchange TEXT NOT NULL,
  UNIQUE (symbol, exchange),
  name TEXT, sector TEXT, industry TEXT, currency TEXT DEFAULT 'USD',
  is_active BOOLEAN NOT NULL DEFAULT true,
  meta JSONB NOT NULL DEFAULT '{}'
);
price_bars (
  ticker_id TEXT NOT NULL REFERENCES tickers,
  bar_date  DATE NOT NULL,
  open NUMERIC(18,6), high NUMERIC(18,6), low NUMERIC(18,6),
  close NUMERIC(18,6) NOT NULL, adj_close NUMERIC(18,6) NOT NULL,
  volume BIGINT,
  snapshot_id TEXT NOT NULL,                 -- content-addressed provenance
  PRIMARY KEY (ticker_id, bar_date)
);
```

### reports (envelope from API.md §4)
```sql
reports (
  report_id   TEXT PRIMARY KEY,
  ticker_id   TEXT REFERENCES tickers,       -- NULL for sector_overview
  sector      TEXT,                          -- set when ticker_id is NULL
  report_type TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  title       TEXT NOT NULL,
  author_agent_id TEXT NOT NULL REFERENCES agents,
  author_model TEXT,
  agent_run_id TEXT REFERENCES agent_runs,
  status      TEXT NOT NULL DEFAULT 'draft'
              CHECK (status IN ('draft','submitted','approved','published','rejected')),
  verdict     JSONB,                         -- {rating, confidence, horizon_days, price_target, one_liner}
  body        JSONB NOT NULL,
  provenance  JSONB NOT NULL DEFAULT '[]',
  tags        TEXT[] NOT NULL DEFAULT '{}',
  supersedes_report_id TEXT REFERENCES reports,
  reviewed_by TEXT, review_note TEXT,
  published_at TIMESTAMPTZ,
  content_hash TEXT NOT NULL                 -- sha256 of canonical body, dedupe + audit
);
CREATE INDEX ON reports (ticker_id, status, created_at DESC);
CREATE INDEX ON reports (author_agent_id, created_at DESC);
```

### report_chunks (RAG)
```sql
report_chunks (
  chunk_id  TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES reports ON DELETE CASCADE,
  ticker_symbol TEXT, section TEXT, seq INT NOT NULL,
  text      TEXT NOT NULL,
  embedding VECTOR(768),                     -- pgvector; sqlite-vec virtual table in dev
  embed_model TEXT NOT NULL DEFAULT 'nomic-embed-text',
  UNIQUE (report_id, seq)
);
-- HNSW index in Postgres; sqlite-vec handles its own.
```

### indexes / scores / weights / backtests
```sql
index_definitions (                          -- registry row per code-defined index
  index_key   TEXT PRIMARY KEY,              -- 'value', 'momentum', ...
  version     TEXT NOT NULL,                 -- bump when formula changes
  direction   TEXT NOT NULL CHECK (direction IN ('higher_better','lower_better')),
  params      JSONB NOT NULL DEFAULT '{}',
  description TEXT NOT NULL
);
index_scores (
  ticker_id TEXT NOT NULL REFERENCES tickers,
  index_key TEXT NOT NULL REFERENCES index_definitions,
  score_date DATE NOT NULL,
  raw_value  DOUBLE PRECISION,               -- pre-normalization
  score      DOUBLE PRECISION NOT NULL,      -- normalized 0..100 cross-sectional
  inputs_digest TEXT NOT NULL,               -- reproducibility
  PRIMARY KEY (ticker_id, index_key, score_date)
);
weight_profiles (
  profile_id TEXT PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,                 -- 'default', 'momentum-heavy'
  weights JSONB NOT NULL,                    -- {"value":0.25,"momentum":0.25,...} must sum to 1
  is_default BOOLEAN NOT NULL DEFAULT false,
  created_by TEXT NOT NULL
);
composite_scores (
  ticker_id TEXT NOT NULL, profile_id TEXT NOT NULL REFERENCES weight_profiles,
  score_date DATE NOT NULL,
  score DOUBLE PRECISION NOT NULL, rank INT NOT NULL,
  PRIMARY KEY (ticker_id, profile_id, score_date)
);
backtest_runs (
  backtest_id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES weight_profiles,
  from_date DATE NOT NULL, to_date DATE NOT NULL,
  universe TEXT[] NOT NULL,
  rebalance TEXT NOT NULL DEFAULT 'weekly',
  config JSONB NOT NULL,                     -- top_n, cost_bps, benchmark
  snapshot_id TEXT NOT NULL, code_version TEXT NOT NULL,   -- reproducibility pair
  status TEXT NOT NULL DEFAULT 'queued',
  metrics JSONB,                             -- {total_return, sharpe, max_dd, hit_rate, benchmark_return}
  artifact_path TEXT                         -- data/backtests/bt_.../
);
```

### agent_runs / audit_events
```sql
agent_runs (
  run_id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES agents,
  task TEXT NOT NULL,                        -- 'deep_dive:NVDA'
  input_digest TEXT,
  status TEXT NOT NULL DEFAULT 'running',    -- running|succeeded|failed|abandoned
  summary TEXT, tokens_used BIGINT,
  started_at TIMESTAMPTZ NOT NULL, ended_at TIMESTAMPTZ
);
audit_events (                               -- append-only; no UPDATE/DELETE grants
  event_id TEXT PRIMARY KEY,
  actor_kind TEXT NOT NULL,                  -- 'agent'|'operator'|'system'
  actor_id TEXT, run_id TEXT,
  action TEXT NOT NULL,                      -- 'report.submit', 'auth.denied', ...
  entity_type TEXT, entity_id TEXT,
  payload JSONB NOT NULL DEFAULT '{}',
  at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### jobs (worker queue)
```sql
jobs (
  job_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL, payload JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',     -- queued|running|done|failed
  attempts INT NOT NULL DEFAULT 0, max_attempts INT NOT NULL DEFAULT 3,
  run_after TIMESTAMPTZ, locked_by TEXT, locked_at TIMESTAMPTZ,
  error TEXT
);
```

### subscriptions (phase 4 — created by migration, unused until flag on)
```sql
subscribers (
  subscriber_id TEXT PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  stripe_customer_id TEXT UNIQUE
);
subscriptions (
  subscription_id TEXT PRIMARY KEY,
  subscriber_id TEXT NOT NULL REFERENCES subscribers,
  stripe_subscription_id TEXT UNIQUE NOT NULL,
  tier TEXT NOT NULL CHECK (tier IN ('free','pro','quant')),
  status TEXT NOT NULL,                      -- mirrors Stripe status verbatim
  current_period_end TIMESTAMPTZ NOT NULL
);
entitlements (
  subscriber_id TEXT NOT NULL, feature TEXT NOT NULL,   -- 'reports.full', 'scores.api', ...
  PRIMARY KEY (subscriber_id, feature)
);
stripe_events (                              -- webhook idempotency ledger
  stripe_event_id TEXT PRIMARY KEY,
  type TEXT NOT NULL, processed_at TIMESTAMPTZ NOT NULL,
  payload JSONB NOT NULL
);
```

## 3. Multi-agent workspace (your item 4)

Claude & Gemini research artifacts that aren't API-shaped (scratch notes,
model files, long transcripts) live in the filesystem, not the DB:

```
data/workspaces/claude/...     data/workspaces/gemini/...
```

The DB link is `agent_runs.run_id` — agents write `run_id` into a
`MANIFEST.json` in their workspace folder so any file is traceable back to
the run and any run to its files. Workspaces (including MANIFESTs) are
fully gitignored: they can contain raw fetched content and scratch notes
that don't belong in a public repo. Traceability lives in the DB audit
trail, not in git.

## 4. Migration policy

- Alembic, one revision per PR, always reversible in dev.
- SQLite and Postgres both exercised in CI (the integration matrix).
- JSONB fields are the escape valve for schema evolution; anything queried
  hot gets promoted to a real column via migration.
