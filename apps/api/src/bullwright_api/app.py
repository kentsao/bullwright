"""App factory. The v1 API surface is documented in docs/API.md; the
committed docs/openapi.json is generated from this app (CI checks drift)."""

from bullwright_core.ids import new_id
from bullwright_db import make_engine, make_session_factory
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from bullwright_api.errors import Problem, install_handlers, problem_response
from bullwright_api.routes import agents_meta, meta, ops, quant, reports, runs, search, tickers
from bullwright_api.settings import settings


def create_app(engine: Engine | None = None, embedder: object | None = None) -> FastAPI:
    cfg = settings()
    app = FastAPI(
        title="Bullwright API",
        version="1.0",
        description=(
            "Stock research, forged by agents. Agents write via this API only; "
            "operator approval gates publication. Bullwright is a research toy — "
            "nothing here is investment advice."
        ),
        docs_url="/docs" if cfg.env == "dev" else None,
        redoc_url=None,
    )
    engine = engine or make_engine(cfg.db_url)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    if embedder is None:
        from bullwright_rag import OllamaEmbedder

        embedder = OllamaEmbedder()
    app.state.embedder = embedder

    @app.middleware("http")
    async def request_id_and_size_cap(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = new_id("req")
        # NUL bytes are legal in URLs but not in Postgres text — reject at
        # the boundary so probes get a 4xx on every backend (rule S8).
        from urllib.parse import unquote

        if "\x00" in unquote(request.url.path) or "\x00" in unquote(request.url.query or ""):
            return problem_response(
                request, Problem(400, "NUL byte in request URL", kind="bad-request")
            )
        length = request.headers.get("content-length")
        if length and int(length) > cfg.max_request_bytes:
            return problem_response(
                request, Problem(413, "Request body too large", kind="payload-too-large")
            )
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    install_handlers(app)
    v1_prefix = "/v1"
    app.include_router(meta.router, prefix=v1_prefix)
    app.include_router(reports.router, prefix=v1_prefix)
    app.include_router(tickers.router, prefix=v1_prefix)
    app.include_router(runs.router, prefix=v1_prefix)
    app.include_router(search.router, prefix=v1_prefix)
    app.include_router(quant.router, prefix=v1_prefix)
    app.include_router(agents_meta.router, prefix=v1_prefix)
    if cfg.env == "dev":
        # Operator troubleshooting dashboard — never mounted outside dev
        # (docs/ARCHITECTURE.md §5b). Unauthenticated by design: dev binds
        # to localhost and the surface is read-only.
        app.include_router(ops.router)

    @app.get("/", include_in_schema=False)
    def root() -> JSONResponse:
        return JSONResponse({"name": "bullwright", "api": "/v1", "docs": "/docs"})

    return app
