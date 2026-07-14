"""Model clients. OllamaModelClient uses native tool calling (H1) and
optional thinking (H8) — verified capabilities of gemma4:12b-mlx."""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx2 as httpx


class ModelError(Exception):
    pass


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ModelTurn:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    thinking: str | None = None


class ModelClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        think: bool = False,
    ) -> ModelTurn: ...


class OllamaModelClient:
    def __init__(self, url: str | None = None, model: str | None = None) -> None:
        self.url = (url or os.environ.get("BW_OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.environ.get("BW_LOCAL_MODEL", "gemma4:12b-mlx")

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        think: bool = False,
    ) -> ModelTurn:
        try:
            resp = httpx.post(
                f"{self.url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "tools": tools,
                    "think": think,
                    "stream": False,
                },
                timeout=300.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ModelError(f"ollama chat failed: {e}") from e
        message = resp.json().get("message", {})
        calls = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):  # some runtimes stringify
                try:
                    args = json.loads(args)
                except ValueError as e:
                    raise ModelError(f"unparseable tool arguments: {args[:200]}") from e
            calls.append(ToolCall(name=str(fn.get("name", "")), args=dict(args)))
        return ModelTurn(
            content=message.get("content") or None,
            tool_calls=calls,
            thinking=message.get("thinking") or None,
        )
