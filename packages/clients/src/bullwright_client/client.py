"""Typed API client. Used by agent scripts AND by tests — contract drift
breaks tests before it breaks agents (docs/AGENT_SKILLS.md §2)."""

import hashlib
import json
import os
from typing import Any

import httpx2 as httpx


class ApiError(Exception):
    """Carries the RFC7807 problem body so callers can react precisely."""

    def __init__(self, status: int, problem: dict[str, Any]) -> None:
        self.status = status
        self.problem = problem
        super().__init__(f"{status}: {problem.get('title', 'API error')}")


def _idempotency_key(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256-" + hashlib.sha256(canonical.encode()).hexdigest()[:32]


class BullwrightClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        base_url = base_url or os.environ.get("BW_API_URL", "http://127.0.0.1:8600/v1")
        api_key = api_key or os.environ.get("BW_API_KEY", "")
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=timeout,
            transport=transport,
        )

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise ApiError(0, {"title": f"connection failed: {e}"}) from e
        if resp.status_code >= 400:
            try:
                problem = resp.json()
            except ValueError:
                problem = {"title": resp.text[:200]}
            raise ApiError(resp.status_code, problem)
        return resp.json() if resp.content else None

    # --- agent runs ---
    def start_run(self, task: str, input_digest: str | None = None) -> dict[str, Any]:
        return self._call("POST", "/agent-runs", json={"task": task, "input_digest": input_digest})  # type: ignore[no-any-return]

    def finish_run(
        self, run_id: str, status: str, summary: str | None = None, tokens_used: int | None = None
    ) -> dict[str, Any]:
        return self._call(  # type: ignore[no-any-return]
            "PATCH",
            f"/agent-runs/{run_id}",
            json={"status": status, "summary": summary, "tokens_used": tokens_used},
        )

    # --- reports ---
    def create_report(self, envelope: dict[str, Any]) -> dict[str, Any]:
        return self._call(  # type: ignore[no-any-return]
            "POST",
            "/reports",
            json=envelope,
            headers={"Idempotency-Key": _idempotency_key(envelope)},
        )

    def get_report(self, report_id: str) -> dict[str, Any]:
        return self._call("GET", f"/reports/{report_id}")  # type: ignore[no-any-return]

    def submit_report(self, report_id: str) -> dict[str, Any]:
        return self._call("POST", f"/reports/{report_id}/submit")  # type: ignore[no-any-return]

    def list_reports(self, **filters: Any) -> dict[str, Any]:
        params = {k: v for k, v in filters.items() if v is not None}
        return self._call("GET", "/reports", params=params)  # type: ignore[no-any-return]

    # --- search / market ---
    def search(self, q: str, ticker: str | None = None, k: int = 8) -> dict[str, Any]:
        params: dict[str, Any] = {"q": q, "k": k}
        if ticker:
            params["ticker"] = ticker
        return self._call("GET", "/search", params=params)  # type: ignore[no-any-return]

    def list_tickers(self) -> list[dict[str, Any]]:
        return self._call("GET", "/tickers")  # type: ignore[no-any-return]

    def version(self) -> dict[str, Any]:
        return self._call("GET", "/version")  # type: ignore[no-any-return]
