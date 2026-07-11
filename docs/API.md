# Bullwright — API Specification

**Version:** v1 (0.1-draft) · **Base URL:** `http://127.0.0.1:8600/v1`

This is the contract agents build against. It is intentionally small and
boring. The generated OpenAPI document (`docs/openapi.json`, committed) is
the machine-readable twin of this file; CI fails if they drift.

## 1. Conventions

- JSON only. `Content-Type: application/json` required on writes.
- IDs are ULIDs (sortable, no coordination): `rep_01J...`, `tkr_...`,
  `run_...`, `bt_...`, `wp_...`.
- Timestamps: RFC 3339 UTC.
- Pagination: `?limit=` (default 20, max 100) + `?cursor=`; responses carry
  `next_cursor`.
- Errors (RFC 7807 style):

```json
{
  "type": "https://bullwright.dev/errors/validation",
  "title": "Report body failed schema validation",
  "status": 422,
  "detail": "body.thesis: field required",
  "instance": "req_01J8...",
  "errors": [{"loc": "body.thesis", "msg": "field required"}]
}
```

- Idempotency: writes accept an `Idempotency-Key` header; the same key +
  same body returns the original response (24 h window). Agent skills
  ALWAYS send one — retries are the norm in agent loops.
- Strictness: unknown fields on write are **rejected** (422), not ignored.
  This catches agent hallucinated fields early.

## 2. Versioning & deprecation

- Path-versioned (`/v1/`). Additive changes (new optional fields, new
  endpoints) do not bump the version. Breaking changes create `/v2/` and
  `/v1/` keeps working for ≥90 days with a `Deprecation` header.

## 3. Authentication & scopes

`Authorization: Bearer bw_live_<32 bytes base62>` (or `bw_test_`).

Keys are minted by the operator CLI (`bw keys create --agent claude
--scopes reports:write,search:read`), shown once, stored hashed. Scopes:

| Scope | Grants |
|---|---|
| `reports:write` | create/update own drafts, submit |
| `reports:read` | read reports (drafts only if owned) |
| `search:read` | RAG search |
| `market:read` | tickers, prices, scores |
| `backtest:run` | trigger backtests |
| `admin` | operator only: approve/publish/reject, key mgmt, weights |

Agents never get `admin`. Rate limits (per key): 60 req/min read,
10 req/min write, 5 concurrent. `429` includes `Retry-After`.

## 4. The Report envelope (heart of the system)

```json
{
  "report_id": "rep_01J8Z...",
  "ticker": "NVDA",
  "report_type": "company_deep_dive",
  "schema_version": "1.0",
  "title": "NVDA: the moat is the software",
  "author": {"kind": "agent", "name": "claude", "model": "claude-fable-5"},
  "status": "draft",
  "verdict": {
    "rating": "buy",              // strong_buy|buy|hold|sell|strong_sell
    "confidence": 0.7,            // 0..1
    "horizon_days": 180,
    "price_target": 210.0,        // optional
    "one_liner": "Datacenter demand durable through 2027."
  },
  "body": { /* validated against report_type JSON Schema */ },
  "provenance": [
    {"kind": "url", "ref": "https://...", "accessed_at": "..."},
    {"kind": "filing", "ref": "0001045810-26-000023"},
    {"kind": "data_snapshot", "ref": "snap_sha256:ab12..."}
  ],
  "tags": ["semis", "ai-capex"],
  "supersedes": null,             // report_id for thesis_update chains
  "created_at": "...", "updated_at": "...",
  "review": {"reviewed_by": null, "note": null}   // set on approve/reject
}
```

Rules:
- `verdict` and ≥1 `provenance` entry are **required** for `submit`.
- `body` is validated against `packages/core/schemas/report_types/
  <report_type>.schema.json`. New report type = new schema file + registry
  entry; the API picks it up without code changes.
- Body content is markdown-in-JSON for prose fields; raw HTML is rejected.

### Report status machine

```
draft ──submit──▶ submitted ──approve──▶ approved ──publish──▶ published
  ▲                   │
  └────revise─────────┘──reject──▶ rejected (terminal, reason required)
```

Agent scopes can do `submit` and `revise` (of own reports). `approve`,
`reject`, `publish` require `admin`.

## 5. Endpoints

### Reports
| Method & path | Scope | Notes |
|---|---|---|
| `POST /reports` | reports:write | create draft; full envelope minus server fields |
| `GET /reports` | reports:read | filters: `ticker`, `status`, `report_type`, `author`, `since` |
| `GET /reports/{id}` | reports:read | |
| `PATCH /reports/{id}` | reports:write | own drafts/submitted only; JSON merge patch |
| `POST /reports/{id}/submit` | reports:write | validates verdict+provenance |
| `POST /reports/{id}/approve` | admin | |
| `POST /reports/{id}/reject` | admin | body: `{reason}` |
| `POST /reports/{id}/publish` | admin | enqueues blog_export |
| `GET /reports/{id}/render` | reports:read | sanitized markdown as it will appear on blog |

### Tickers & market data
| | | |
|---|---|---|
| `POST /tickers` | admin | add to watchlist `{symbol, exchange, sector}` |
| `GET /tickers` / `GET /tickers/{symbol}` | market:read | includes latest composite score |
| `GET /tickers/{symbol}/prices?from=&to=` | market:read | daily OHLCV |
| `GET /tickers/{symbol}/scores?profile=` | market:read | per-index + composite time series |

### Indexes, weights, backtests
| | | |
|---|---|---|
| `GET /indexes` | market:read | registered indexes + methodology metadata |
| `GET /weight-profiles` / `POST /weight-profiles` | market:read / admin | see INDEXES.md §4 |
| `POST /backtests` | backtest:run | `{weight_profile_id, from, to, universe?, rebalance:"weekly"}` → `202 {backtest_id}` |
| `GET /backtests/{id}` | market:read | status + metrics + artifact link |

### Search (RAG)
| | | |
|---|---|---|
| `GET /search?q=&ticker=&type=&since=&k=8` | search:read | returns chunks with `{text, score, report_id, section, citation}` |

### Agent ops
| | | |
|---|---|---|
| `POST /agent-runs` | reports:write | agent announces a work session `{task, input_digest}` → `run_id`; skills attach `run_id` to all subsequent writes (audit thread) |
| `PATCH /agent-runs/{id}` | reports:write | close with `{status, summary, tokens_used?}` |
| `GET /healthz`, `GET /version` | none | liveness; version returns git sha + schema versions |

### Webhooks (Stripe — flagged)
`POST /webhooks/stripe` — signature-verified; see SUBSCRIPTION.md.

## 6. Security requirements (testable)

- [S1] All non-health endpoints 401 without a valid key.
- [S2] Scope violations return 403 with the missing scope named.
- [S3] Agent A cannot read/patch agent B's drafts (404, not 403 — don't leak existence).
- [S4] Payloads > 1 MiB rejected 413. Report body > 256 KiB rejected 422.
- [S5] Raw HTML / `<script>` in any markdown field → 422.
- [S6] Rate limit exceeded → 429 + Retry-After; verified per key not global.
- [S7] Key revocation effective ≤ 5 s (no long-lived cache).
- [S8] SQL injection & path traversal probes in all string params → 4xx, never 500.
- [S9] Stripe webhook without valid signature → 400, no side effects.
- [S10] Audit row written for every state transition incl. rejected auth attempts (key prefix only, never full key).
