# Bullwright

*Stock research, forged by agents.*

Bullwright is a self-hosted framework for tracking stocks, generating and
publishing company/product research reports, and letting AI agents (Claude,
Gemini, local Ollama models) do the research legwork through a well-defined
API and skill set. It ships as a template/monorepo you can run entirely on
your own machine, with a clear path to a cloud deployment later.

This repo is currently in the **spec phase**. Nothing here is implemented
yet — the goal of this phase is to nail down the contracts (API, DB schema,
agent skills, index protocol, test plan) before writing code, so the build
goes fast and doesn't need to be re-architected halfway through.

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

## Status

- [x] Spec + test plan (reviewed; decisions in [ADR-0001](docs/adr/0001-initial-stack.md))
- [x] Phase 1 — core API + DB + blog (`v0.1.0`)
- [x] Phase 2 — agent skills, bw-agent CLI, RAG search, gemma harness, ops dashboard
- [ ] Phase 3 — quant indexes + backtest
- [ ] Phase 4 — UI polish + cloud packaging (billing stays spec-only)

Not deployed to the internet — this is a local-first framework/template.
GitHub is used for version control only (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#github--cicd)).

### Troubleshooting

Run the API (`uv run bw serve`) and open **http://127.0.0.1:8600/ops** —
overview counts, the review queue, job errors, agent runs, and the audit
tail, straight from the live DB (dev-mode only, read-only).
