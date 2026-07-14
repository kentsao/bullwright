"""VectorStore protocol + the portable DB-backed implementation.

v1 stores embeddings as JSON lists in report_chunks and ranks with numpy
cosine in-process — well inside the <2s @ 10k-chunks budget (PLAN.md
phase 2 note). sqlite-vec / pgvector become drop-in adapters behind the
same protocol when scale demands.
"""

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from bullwright_core.ids import new_id
from bullwright_db.models import ReportChunk
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from bullwright_rag.chunker import Chunk


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    report_id: str
    ticker: str | None
    section: str | None
    seq: int
    text: str
    score: float

    @property
    def citation(self) -> str:
        return f"{self.report_id}#{self.section or 'body'}.{self.seq}"


class VectorStore(Protocol):
    def upsert_report(
        self,
        report_id: str,
        ticker: str | None,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        embed_model: str,
    ) -> int: ...

    def search(
        self, query_vec: list[float], k: int = 8, ticker: str | None = None
    ) -> list[SearchHit]: ...


class DbVectorStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_report(
        self,
        report_id: str,
        ticker: str | None,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        embed_model: str,
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        self.session.execute(delete(ReportChunk).where(ReportChunk.report_id == report_id))
        for chunk, vec in zip(chunks, embeddings, strict=True):
            self.session.add(
                ReportChunk(
                    chunk_id=new_id("chk"),
                    report_id=report_id,
                    ticker_symbol=ticker,
                    section=chunk.section,
                    seq=chunk.seq,
                    text=chunk.text,
                    embedding=vec,
                    embed_model=embed_model,
                )
            )
        return len(chunks)

    def search(
        self, query_vec: list[float], k: int = 8, ticker: str | None = None
    ) -> list[SearchHit]:
        q = select(ReportChunk)
        if ticker:
            q = q.where(ReportChunk.ticker_symbol == ticker.upper())
        rows = self.session.scalars(q).all()
        if not rows:
            return []
        matrix = np.array([r.embedding for r in rows], dtype=np.float32)
        query = np.array(query_vec, dtype=np.float32)
        denom = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(query) or 1.0)
        denom[denom == 0] = 1.0
        scores = matrix @ query / denom
        order = np.argsort(-scores)[:k]
        return [
            SearchHit(
                chunk_id=rows[i].chunk_id,
                report_id=rows[i].report_id,
                ticker=rows[i].ticker_symbol,
                section=rows[i].section,
                seq=rows[i].seq,
                text=rows[i].text,
                score=float(scores[i]),
            )
            for i in order
        ]
