#!/usr/bin/env bash
# Workspace sync with a macOS/iCloud workaround.
#
# This repo may live in an iCloud-synced folder (e.g. Desktop). The file
# provider daemon intermittently sets the UF_HIDDEN flag on files in
# .venv/site-packages, and Python's `site` module SILENTLY SKIPS hidden
# .pth files — making editable workspace packages unimportable
# (ModuleNotFoundError even though `uv pip list` shows them installed).
#
# chflags loses the race against the daemon, so instead we install a
# sitecustomize.py that re-reads the editable .pth files itself: module
# imports don't check UF_HIDDEN, only .pth processing does.
# Linux/CI never hits any of this; the shim is inert there.
set -euo pipefail
cd "$(dirname "$0")/.."

uv sync --all-packages --dev "$@"

for sp in .venv/lib/python*/site-packages; do
  cat > "$sp/sitecustomize.py" <<'PY'
"""Bullwright dev shim (written by scripts/sync.sh — not committed).

Re-applies editable-install .pth entries that Python's site module may
have skipped because macOS/iCloud set UF_HIDDEN on them."""

import pathlib
import sys

_sp = pathlib.Path(__file__).parent
for _pth in _sp.glob("_editable_impl_*.pth"):
    for _line in _pth.read_text().splitlines():
        _line = _line.strip()
        if _line and _line not in sys.path and pathlib.Path(_line).is_dir():
            sys.path.insert(0, _line)
PY
done

echo "sync ok (editable-path shim refreshed)"
