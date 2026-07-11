"""Export PUBLISHED reports to the Astro content directory.

This is the single sanctioned path from DB to blog (docs/ARCHITECTURE.md
§5). Only `published` reports leave the DB. Defense in depth on top of the
API's ingest-time HTML rejection (S5): anything tag-shaped is escaped at
export, and Astro sanitizes at render. Three layers, no raw HTML on the
blog.
"""

import json
import re
from datetime import UTC
from pathlib import Path
from typing import Any

from bullwright_db.models import Agent, Report, Ticker
from sqlalchemy import select
from sqlalchemy.orm import Session

_TAGISH = re.compile(r"<(?=[a-zA-Z/!])")


def _escape(text: str) -> str:
    return _TAGISH.sub("&lt;", text)


def _section_title(key: str) -> str:
    return key.replace("_", " ").title()


def body_to_markdown(body: dict[str, Any]) -> str:
    """Report-type agnostic: dict keys become sections, lists become
    bullets. New report types render without touching this code."""
    parts: list[str] = []
    for key, value in body.items():
        parts.append(f"## {_section_title(key)}\n")
        if isinstance(value, list):
            parts.extend(f"- {_escape(str(item))}" for item in value)
            parts.append("")
        else:
            parts.append(f"{_escape(str(value))}\n")
    return "\n".join(parts)


def export_published(session: Session, out_dir: Path) -> int:
    reports_dir = out_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    for stale in reports_dir.glob("*.md"):
        stale.unlink()  # full regeneration: the DB is the source of truth

    rows = session.scalars(
        select(Report).where(Report.status == "published").order_by(Report.published_at)
    ).all()
    for row in rows:
        symbol = None
        if row.ticker_id:
            t = session.get(Ticker, row.ticker_id)
            symbol = t.symbol if t else None
        author = session.get(Agent, row.author_agent_id)
        author_name = author.name if author else "unknown"
        if row.published_at is None:  # unreachable: status filter guarantees it
            continue
        pub = row.published_at
        pub = pub if pub.tzinfo else pub.replace(tzinfo=UTC)
        frontmatter = {
            "title": _escape(row.title),
            "reportId": row.report_id,
            "ticker": symbol,
            "sector": row.sector,
            "reportType": row.report_type,
            "author": author_name,
            "authorModel": row.author_model,
            "verdict": row.verdict,
            "tags": [str(t) for t in row.tags],
            "publishedAt": pub.isoformat(),
            "supersedes": row.supersedes_report_id,
            "provenanceCount": len(row.provenance),
        }
        scope = (symbol or row.sector or "general").lower()
        slug = f"{pub.date().isoformat()}-{scope}-{row.report_id[-8:].lower()}"
        content = (
            "---\n"
            + json.dumps(frontmatter, indent=2, default=str)
            + "\n---\n\n"
            + body_to_markdown(row.body)
        )
        (reports_dir / f"{slug}.md").write_text(content, encoding="utf-8")
    return len(rows)
