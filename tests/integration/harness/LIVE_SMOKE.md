# Harness live smoke (manual gate — not CI)

Proves the real local model end-to-end: gemma4:12b-mlx drives the
whitelisted tools and lands a schema-valid `news_flash` in `submitted`.

## Prerequisites

- `ollama` running with `gemma4:12b-mlx` and `nomic-embed-text` pulled
- API up: `uv run bw serve` (localhost:8600)
- A `local`-kind agent with a key:
  `uv run bw agents create gemma-local --kind local --model gemma4:12b-mlx`
  `uv run bw keys create --agent gemma-local --scopes reports:write,reports:read,search:read`

## Run

```bash
cat > data/inbox/news/$(date +%F).json <<'EOF'
[
  {"ticker": "NVDA", "headline": "...", "source": "<publisher ref>", "date": "..."}
]
EOF

export BW_API_URL=http://127.0.0.1:8600/v1
export BW_API_KEY=<the gemma-local key>
uv run bw-harness run news_sweep --input data/inbox/news/$(date +%F).json
```

## Pass criteria

- exit code 0, `status: succeeded`, exactly one report id in `reports`
- `/ops/queue` shows the report in `submitted` with a conservative
  verdict (confidence ≤ 0.6)
- `/ops/runs` shows the harness run `succeeded`
- turn count ≤ 10; no tool errors in `data/harness/news_sweep/*/state.json`
