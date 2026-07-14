from typing import Annotated

from bullwright_rag import DbVectorStore, EmbedderError
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from bullwright_api.auth.deps import SessionDep, require_scope
from bullwright_api.auth.keys import Principal
from bullwright_api.errors import Problem

router = APIRouter(tags=["search"])

SearchScope = Annotated[Principal, Depends(require_scope("search:read"))]


class SearchHitOut(BaseModel):
    text: str
    score: float
    report_id: str
    ticker: str | None
    section: str | None
    citation: str


class SearchOut(BaseModel):
    query: str
    hits: list[SearchHitOut]


@router.get("/search", response_model=SearchOut)
def search(
    request: Request,
    session: SessionDep,
    principal: SearchScope,
    q: Annotated[str, Query(min_length=2, max_length=500)],
    ticker: str | None = None,
    k: Annotated[int, Query(ge=1, le=20)] = 8,
) -> SearchOut:
    embedder = request.app.state.embedder
    try:
        query_vec = embedder.embed([q])[0]
    except EmbedderError as e:
        raise Problem(
            503,
            "Embedding backend unavailable",
            kind="upstream-unavailable",
            detail=str(e),
            headers={"Retry-After": "10"},
        ) from e
    hits = DbVectorStore(session).search(query_vec, k=k, ticker=ticker)
    return SearchOut(
        query=q,
        hits=[
            SearchHitOut(
                text=h.text,
                score=round(h.score, 4),
                report_id=h.report_id,
                ticker=h.ticker,
                section=h.section,
                citation=h.citation,
            )
            for h in hits
        ],
    )
