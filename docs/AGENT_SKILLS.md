# Bullwright — Agent Usage Spec (Skills, Scripts, Harness & Loop Engineering)

**Version:** 0.1-draft · **Status:** awaiting review

Three agent classes, one contract: agents interact with Bullwright **only**
through the v1 API using scoped keys, and every work session is threaded
through an `agent_run` for auditability.

| Class | Examples | How they run |
|---|---|---|
| Interactive cloud | Claude Code, Gemini CLI | Human-invoked; load a skill, call scripts |
| Autonomous local | Ollama `gemma4:12b-mlx` | Unattended via `agents/harness/` loop |
| Human | you | operator CLI (`bw`), full admin |

Verified local model (`ollama show gemma4:12b-mlx`, 2026-07-11): 12.4B
params, **262k context**, native **tool calling** and thinking, nvfp4
quant. The harness design below assumes these capabilities.

## 1. Skills (`agents/skills/`)

Claude-style skill folders (SKILL.md + resources). Gemini gets the same
content via a generated `GEMINI.md` adapter — single source of truth,
generated artifacts, never hand-forked.

| Skill | Purpose | Key scripts used |
|---|---|---|
| `bw-report-writer` | Research a ticker → produce a schema-valid report → upload as draft → submit | `bw-agent report create/validate/submit` |
| `bw-earnings-review` | Quarter review flavor; pulls prior thesis via RAG first | `bw-agent search`, `report` |
| `bw-thesis-update` | Update existing thesis; must set `supersedes` | `bw-agent report get`, `search` |
| `bw-rag-search` | Answer questions from the report corpus with citations | `bw-agent search` |
| `bw-screener` | Rank watchlist by composite score, propose next deep-dive targets | `bw-agent scores`, `tickers` |
| `bw-backtest` | Configure + run a backtest, interpret metrics | `bw-agent backtest run/get` |

**Skill authoring rules (enforced by review):**

1. SKILL.md states: goal, required scopes, exact script invocations,
   the JSON Schema of what the agent must produce, and 1 worked example.
2. Skills never embed API keys or URLs — scripts read `BW_API_URL` /
   `BW_API_KEY` from environment.
3. Skills instruct the agent to **validate locally before uploading**
   (`bw-agent report validate draft.json`) — cheap failure beats a 422 loop.
4. Skills require the provenance list to be built *while researching*,
   not reconstructed at the end.
5. Skills end with a self-check checklist (verdict present? sources ≥ 3?
   no HTML in markdown? confidence justified in body?).

## 2. Scripts (`agents/scripts/`)

One CLI, `bw-agent`, built on `packages/clients` (the same typed client the
tests use — contract drift breaks tests, not agents):

```
bw-agent run start --task "deep_dive:NVDA"        → prints run_id
bw-agent report create --file draft.json          (attaches run_id)
bw-agent report validate --file draft.json        (offline, JSON Schema)
bw-agent report submit rep_01J...
bw-agent search "prior NVDA margin thesis" --ticker NVDA -k 8
bw-agent prices NVDA --from 2026-01-01
bw-agent scores --profile default --top 10
bw-agent backtest run --profile default --from 2026-01-01 --to 2026-07-01
bw-agent run finish --status succeeded --summary "..."
```

Design rules: every command exits nonzero with a machine-readable JSON error
on failure; every mutating command sends an `Idempotency-Key` derived from
content hash; `--dry-run` everywhere.

## 3. Harness engineering (local gemma loop)

`agents/harness/` runs the local model unattended. Architecture:

```
tasks.yaml ─▶ scheduler ─▶ task runner ─▶ Ollama /api/chat (gemma4:12b-mlx)
                                │   ▲            │ native tool calls
                                ▼   │            │
                          tool executor ◀────────┘
                          (whitelisted bw-agent tools only)
```

**H1 — Tool whitelist.** The model never gets a shell. The harness passes
Ollama a fixed tool registry (JSON Schema per tool) mirroring `bw-agent`
subcommands and uses the model's **native tool-calling** capability; the
executor re-validates args against the same schemas before running —
defense in depth, model-emitted args are never trusted.

**H2 — Structured output enforcement.** Tool-call turns are structurally
valid by construction (native tools). Final-answer turns that must be
documents (e.g. a report body) are requested with `format: <json schema>`
and validated against the report-type schema; on failure, retry-with-error
up to 3 attempts, then fail the task. Report bodies are always validated
before any API call.

**H3 — Budgets.** Per task: max turns (default 12), max wall-clock
(default 10 min), max output tokens. Exceeding any budget = task fails
with `budget_exceeded`, run marked `abandoned`, never silent runaway.

**H4 — Context discipline.** gemma4:12b-mlx has a 262k context window, so
this is no longer a correctness constraint — it is retained as a quality/
latency policy. The harness assembles each turn from: task instructions
(fixed) + rolling summary of prior turns (harness-maintained) + the last
2 tool results (truncated to 16 KiB each with a `truncated: true` marker).
Attention quality on a 12B model degrades long before 262k; keep turns lean.

**H5 — Injection stance.** All tool results and RAG chunks are wrapped in
`<data>` fences with a standing instruction that fenced content is never a
command. Tasks touching web content run with write scopes stripped to
drafts-only.

**H6 — Checkpointing.** Harness state (task queue, per-task turn log) is
on disk; a crash resumes from the last completed turn. Turn logs are the
debugging artifact.

**H7 — Suitable work only.** gemma-class tasks: news_flash drafts, tagging,
RAG-answer evaluation, summarization. Deep dives stay with Claude/Gemini.
tasks.yaml declares `min_agent_class` per task type.

**H8 — Thinking budget.** gemma4:12b-mlx supports thinking; the harness
enables it for report-drafting tasks and disables it for high-volume
tagging/classification loops (latency). Thinking content is logged to the
turn log but never sent back into context or included in report bodies.

## 4. Loop engineering

Recurring loops defined in `agents/harness/tasks.yaml`:

| Loop | Cadence | Agent | Pipeline |
|---|---|---|---|
| `news_sweep` | daily | gemma | fetch headlines for watchlist → news_flash drafts → submit |
| `report_tagger` | on submit | gemma | propose tags + section quality flags |
| `score_digest` | weekly | gemma | composite movers summary → draft |
| `earnings_radar` | daily | gemma | flag tickers reporting within 7 days → task for cloud agent |
| `rag_eval` | weekly | gemma | run eval question set, record hit-rate (TEST_PLAN §6) |

Loop rules:

- **L1 idempotent** — every loop derives an `Idempotency-Key` from
  (task, date, input digest); re-running a day is safe.
- **L2 bounded** — one loop iteration = one agent_run with H3 budgets; a
  loop never spawns loops.
- **L3 dead-letter** — 3 consecutive failures of a loop pauses it and
  surfaces in `bw status`; no infinite retry.
- **L4 no self-approval** — loops end at `submitted`. Operator reviews.
  This is the harness-level guarantee behind the human-in-the-loop rule.
- **L5 drift check** — weekly `rag_eval` + agent scorecard trends are the
  early-warning system for silent quality regressions.

## 5. Model routing

| Task | Model | Rationale |
|---|---|---|
| Deep dives, thesis updates | Claude (claude-fable-5) | strongest long-form reasoning |
| Second-opinion coverage | Gemini 2.5 Pro | consensus-diff feature needs a genuinely different model |
| High-volume cheap loops | gemma4:12b-mlx local | free, private, native tools + 262k context, good enough with H2 validation |
| Embeddings | nomic-embed-text local | free, fast |

## 6. Agent scorecard (spec)

Because verdicts are structured: for each published report, at
`horizon_days` (and fixed 30/90d checkpoints) the worker compares realized
adj-close move vs verdict direction. Per agent: directional hit-rate,
mean confidence-weighted return, calibration curve (confidence vs
accuracy). Exposed at `GET /agents/{name}/scorecard` and on the blog.

## 7. Safety invariants (restated, testable)

- A1: no agent key ever has `admin` (CI check on key-mint code paths).
- A2: nothing reaches `published` without operator action (state machine test).
- A3: harness tool registry ⊆ documented `bw-agent` surface (snapshot test).
- A4: fenced-data injection suite passes (security tests, TEST_PLAN §7).
- A5: agents cannot see other agents' drafts (API S3).
