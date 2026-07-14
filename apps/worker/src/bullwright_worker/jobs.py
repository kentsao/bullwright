"""Job handlers. Each takes (session, payload) and returns an optional
human-readable note stored on the job row."""

from pathlib import Path
from typing import Any

from bullwright_db.models import Report, Ticker
from bullwright_rag import DbVectorStore, Embedder, chunk_report_body
from sqlalchemy.orm import Session


def make_embed_report(embedder: Embedder) -> Any:
    def embed_report(session: Session, payload: dict[str, Any]) -> str:
        report = session.get(Report, payload["report_id"])
        if report is None:
            raise RuntimeError(f"report {payload.get('report_id')!r} not found")
        ticker = session.get(Ticker, report.ticker_id) if report.ticker_id else None
        chunks = chunk_report_body(report.body)
        vectors = embedder.embed([c.text for c in chunks]) if chunks else []
        n = DbVectorStore(session).upsert_report(
            report.report_id,
            ticker.symbol if ticker else None,
            chunks,
            vectors,
            embedder.model,
        )
        return f"embedded {n} chunks"

    return embed_report


def blog_export(session: Session, payload: dict[str, Any]) -> str:
    from bullwright_api.export_blog import export_published

    out_dir = Path(payload.get("out_dir", "apps/web/src/content"))
    n = export_published(session, out_dir)
    return f"exported {n} published reports"
