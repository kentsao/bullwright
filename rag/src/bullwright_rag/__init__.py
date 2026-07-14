"""Bullwright RAG subsystem (docs/ARCHITECTURE.md §6)."""

from bullwright_rag.chunker import Chunk, chunk_report_body
from bullwright_rag.embedder import Embedder, EmbedderError, FakeEmbedder, OllamaEmbedder
from bullwright_rag.store import DbVectorStore, SearchHit, VectorStore

__all__ = [
    "Chunk",
    "DbVectorStore",
    "Embedder",
    "EmbedderError",
    "FakeEmbedder",
    "OllamaEmbedder",
    "SearchHit",
    "VectorStore",
    "chunk_report_body",
]
