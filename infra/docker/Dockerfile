# Bullwright backend image — one image, two roles (api / worker), chosen
# by the compose `command`. Build context is the repo root:
#   docker build -f infra/docker/Dockerfile .
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Workspace manifests first for layer caching…
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/db/pyproject.toml packages/db/pyproject.toml
COPY packages/clients/pyproject.toml packages/clients/pyproject.toml
COPY packages/quant/pyproject.toml packages/quant/pyproject.toml
COPY rag/pyproject.toml rag/pyproject.toml
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
COPY agents/harness/pyproject.toml agents/harness/pyproject.toml

# …then sources.
COPY packages packages
COPY rag rag
COPY apps/api apps/api
COPY apps/worker apps/worker
COPY agents agents

RUN uv sync --frozen --no-dev --all-packages --extra postgres || \
    uv sync --frozen --no-dev --all-packages

RUN useradd -m bullwright && mkdir -p /app/data && chown -R bullwright /app
USER bullwright

EXPOSE 8600
# Containers bind 0.0.0.0 INSIDE the network namespace; compose only
# publishes to the host loopback (see compose.yaml ports).
CMD ["uv", "run", "bw", "serve", "--host", "0.0.0.0"]
