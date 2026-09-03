# syntax=docker/dockerfile:1.4
FROM python:3.14-slim AS base
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
WORKDIR /app

FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Self-contained: only games/ pyproject.toml (no workspace, no lockfile needed for build)
COPY services/games/pyproject.toml ./pyproject.toml
RUN uv sync --no-dev --no-install-project

FROM base AS runtime

RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y --no-install-recommends \
        wget \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder --chown=65532:65532 /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Games service assets (preserve services/ package hierarchy)
COPY --chown=65532:65532 shared/ ./shared/
COPY --chown=65532:65532 services/ ./services/
# Self-contained pyproject.toml
COPY --chown=65532:65532 services/games/pyproject.toml ./pyproject.toml

USER 65532

LABEL org.opencontainers_image.source="https://github.com/ivanprytula/cv-rest-mcp-server" \
      org.opencontainers_image.licenses="Apache-2.0"

ENV PORT=8081
EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s CMD wget -qO- http://localhost:$PORT/health || exit 1

CMD ["python", "-m", "services.games.main"]
