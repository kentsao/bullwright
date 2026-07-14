"""Embedding clients behind one protocol. Ollama for real use; the fake is
deterministic for tests (similar prefixes -> similar vectors is NOT a goal
there — it only exercises plumbing)."""

import hashlib
import math
import os
from typing import Protocol

import httpx2 as httpx


class EmbedderError(Exception):
    pass


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    def __init__(self, url: str | None = None, model: str | None = None) -> None:
        self.url = (url or os.environ.get("BW_OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.environ.get("BW_EMBED_MODEL", "nomic-embed-text")

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            resp = httpx.post(
                f"{self.url}/api/embed",
                json={"model": self.model, "input": texts},
                timeout=60.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise EmbedderError(f"ollama embed failed: {e}") from e
        data = resp.json()
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise EmbedderError("ollama embed returned an unexpected shape")
        return embeddings


class FakeEmbedder:
    """Deterministic 64-dim embeddings from token hashes. Texts sharing
    words get similar vectors — enough to make ranking tests meaningful."""

    model = "fake-64"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * 64
            for token in text.lower().split():
                h = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big")
                vec[h % 64] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out
