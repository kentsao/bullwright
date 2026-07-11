"""Phase 0 smoke test — proves the toolchain (uv + pytest + workspace) works."""

import bullwright_core


def test_workspace_imports() -> None:
    assert bullwright_core.__version__
