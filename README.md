# Bullwright

*Stock research, forged by agents.*

Bullwright is a self-hosted framework for tracking stocks, generating and
publishing company/product research reports, and letting AI agents (Claude,
Gemini, local Ollama models) do the research legwork through a well-defined
API and skill set. It ships as a template/monorepo you can run entirely on
your own machine, with a clear path to a cloud deployment later.

The framework is **fully implemented** (v0.5.0): agents research through
a locked-down API, humans approve, reports publish to a static blog,
RAG makes the corpus searchable, news/SEC signals and agent verdicts
feed a six-index quant score, backtests are bit-reproducible, and a
scorecard grades every agent against what prices actually did. Specs
came first and still define every contract — see the table below.

## Start here

| Doc | What it covers |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | Product scope, goals, non-goals, system overview |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Directory layout, service boundaries, data flow |
| [docs/API.md](docs/API.md) | REST API for report upload/retrieval, auth |
| [docs/AGENT_SKILLS.md](docs/AGENT_SKILLS.md) | Skills/scripts agents use, harness & loop engineering |
| [docs/DB_SCHEMA.md](docs/DB_SCHEMA.md) | Database schema (SQLite dev / Postgres prod) |
| [docs/INDEXES.md](docs/INDEXES.md) | Quant index protocol, weighting, backtesting |
| [docs/SUBSCRIPTION.md](docs/SUBSCRIPTION.md) | Stripe subscription/entitlement model |
| [docs/TEST_PLAN.md](docs/TEST_PLAN.md) | Test strategy across all of the above |
| [docs/OPEN_DECISIONS.md](docs/OPEN_DECISIONS.md) | Things that need your call before implementation |

## Quickstart (dev environment)

Bullwright uses [uv](https://docs.astral.sh/uv/) — it manages the virtual
environment, the Python version (pinned to 3.12 via `.python-version`),
and the lockfile in one tool. No conda/pyenv needed.

```bash
brew install uv                 # or: curl -LsSf https://astral.sh/uv/install.sh | sh
./scripts/sync.sh              # uv sync + a macOS .pth-flag workaround (see script)
uv run pytest tests/unit        # run the tests
uv run pre-commit install       # enable secret-scanning commit hooks (do this!)
cp .env.example .env            # local config (never committed)
```

`uv run <cmd>` executes inside the project venv automatically; if you
prefer a classic activated shell: `source .venv/bin/activate`.

## Quick usage (local deployment)

The five-minute path from a fresh clone to a working research system.
Everything binds to `127.0.0.1` — nothing is exposed to the internet.

### 0. One-time prerequisites

```bash
# Ollama with an embedding model (RAG) and a tools-capable chat model
# (harness + sentiment). Any model with native tool calling works; set
# BW_LOCAL_MODEL in .env if yours differs from the default.
ollama pull nomic-embed-text

# Optional: real market data (yfinance is an optional adapter — the
# framework defaults to a deterministic fixture provider)
uv pip install yfinance
```

### 1. Bootstrap the database and your operator identity

```bash
uv run bw db-upgrade          # apply migrations (data/bullwright.db)
uv run bw keys bootstrap      # prints your ADMIN key ONCE — save it
```

### 2. Build a watchlist

```bash
uv run bw tickers add NVDA --exchange NASDAQ --sector semis
uv run bw tickers add MSFT --exchange NASDAQ --sector software
# ... add the names you care about (8-40 works well)
```

### 3. Run the two processes

```bash
uv run bw serve               # API + ops dashboard  → http://127.0.0.1:8600
uv run bw-worker              # jobs + schedule ticker (separate terminal)
```

The worker is what makes schedules fire and background jobs (embedding,
blog export, crawls) run — keep it running. Open
**http://127.0.0.1:8600/ops** for the live dashboard.

### 4. Prices, scores, backtest

```bash
uv run bw quant ingest --provider yfinance --days 400   # or --provider fixture
uv run bw quant score --from 2026-01-05 --to 2026-07-15
uv run bw quant backtest --from 2026-01-05 --to 2026-07-15 --top-n 3
```

### 5. News, SEC filings, sentiment, alerts

Set `BW_EDGAR_UA` in `.env` first (SEC requires a contact email). Then:

```bash
uv run bw signals crawl --provider rss   # news for the whole watchlist
uv run bw signals sec                    # EDGAR filings
uv run bw signals analyze --batch 40     # local-model sentiment scoring
uv run bw signals scan                   # raise alerts → /ops/alerts
```

Or let the worker do all of it on a cadence:

```bash
uv run bw schedules add news-6h          --kind news_crawl        --every 360 --payload '{"provider":"rss"}'
uv run bw schedules add sec-daily        --kind sec_sync          --every 1440
uv run bw schedules add sentiment-hourly --kind sentiment_analyze --every 60 --payload '{"batch":40}'
uv run bw schedules add alerts-hourly    --kind alert_scan        --every 60
uv run bw schedules list
```

### 6. Let agents research

Mint a key per agent, then point any agent (Claude, Gemini, a script)
at the API via the `bw-agent` CLI and the skills in `agents/skills/`:

```bash
uv run bw agents create claude --kind cloud --model claude-fable-5
uv run bw keys create --agent claude --scopes reports:write,reports:read,search:read

export BW_API_URL=http://127.0.0.1:8600/v1
export BW_API_KEY=<the key printed above>
uv run bw-agent ping                     # verify connectivity + auth
```

**Local model as an agent (no cloud, no cost).** Your Ollama model
gets its own identity and key, then runs unattended loops through the
harness — tool-whitelisted, budgeted, and unable to publish by design:

```bash
uv run bw agents create gemma-local --kind local --model gemma4:12b-mlx
uv run bw keys create --agent gemma-local --scopes reports:write,reports:read,search:read

export BW_API_KEY=<the gemma-local key>
export BW_LOCAL_MODEL=gemma4:12b-mlx     # any Ollama model with tool calling

# headlines in, schema-valid submitted drafts out:
uv run bw-harness run news_sweep --input data/inbox/news/2026-07-15.json
```

The same local model also powers news sentiment scoring
(`bw signals analyze`) and RAG embeddings — one Ollama install drives
the whole local stack. Loops are defined in `agents/harness/tasks.yaml`;
add your own with instructions + budgets, no code required.

### 7. Review and publish (the human gate)

Agents can only *submit*. Review the queue at `/ops/queue`, then approve
and publish with your admin key:

```bash
curl -X POST http://127.0.0.1:8600/v1/reports/<report_id>/approve \
     -H "Authorization: Bearer $BW_ADMIN_KEY"
curl -X POST http://127.0.0.1:8600/v1/reports/<report_id>/publish \
     -H "Authorization: Bearer $BW_ADMIN_KEY"
```

### 8. Open the UI

```bash
uv run bw ui        # refreshes blog data, starts the blog dev server
```

That's the whole command: **blog at http://localhost:4321** (score
dashboard, per-ticker charts, consensus diffs, agent scorecard) and the
**ops dashboard at http://127.0.0.1:8600/ops** (review queue, jobs,
alerts, schedules — needs `bw serve` running). For a production build:
`uv run bw export-blog && cd apps/web && npm run build` → static files
in `apps/web/dist/`, host anywhere.

### All-in-one alternative: Docker

```bash
docker compose -f infra/docker/compose.yaml up          # postgres + api + worker
docker compose -f infra/docker/compose.yaml --profile llm up   # + ollama
```

## Status

- [x] Spec + test plan (reviewed; decisions in [ADR-0001](docs/adr/0001-initial-stack.md))
- [x] Phase 1 — core API + DB + blog (`v0.1.0`)
- [x] Phase 2 — agent skills, bw-agent CLI, RAG search, gemma harness, ops dashboard
- [x] Phase 3 — quant indexes + backtest (`v0.3.0`)
- [x] Phase 4 — UI polish + cloud packaging (`v0.4.0`) — MVP complete 🐂
- [x] Phase 5 — news/SEC signals, sentiment index, scheduler, alerts (`v0.5.0`)

Not deployed to the internet — this is a local-first framework/template.
GitHub is used for version control only (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#github--cicd)).

### Troubleshooting

Run the API (`uv run bw serve`) and open **http://127.0.0.1:8600/ops** —
overview counts, the review queue, job errors, agent runs, and the audit
tail, straight from the live DB (dev-mode only, read-only).
