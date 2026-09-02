# syntax=docker/dockerfile:1.4
FROM python:3.14-slim AS base
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
WORKDIR /app

FROM base AS builder
# Digest of the multi-platform manifest for uv 0.12.5 (verified via
# `docker buildx imagetools inspect ghcr.io/astral-sh/uv:0.12.5`).
COPY --from=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

# No RUN --mount=type=cache here: Cloud Build's default runner uses the
# legacy (non-BuildKit) builder. Layer caching on uv.lock covers the deps.
# DEBIAN_FRONTEND inline (not ENV): silences debconf TTY warnings in
# non-interactive builds without leaking the var into the runtime image.
RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project

FROM base AS runtime

RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y --no-install-recommends \
        wget \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libgobject-2.0-0 \
        libglib2.0-0 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder --chown=65532:65532 /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --chown=65532:65532 shared/ ./shared/
COPY --chown=65532:65532 templates/ ./templates/
COPY --chown=65532:65532 static/ ./static/
# .dockerignore reduces data/ to cv.example.json only — the placeholder the
# app serves until a real CV lands in the GCS bucket. Personal data never
# enters the image.
COPY --chown=65532:65532 data/ ./data/
COPY --chown=65532:65532 config/ ./config/
COPY --chown=65532:65532 services/portfolio/ ./services/portfolio/
COPY --chown=65532:65532 pyproject.toml ./

USER 65532

LABEL org.opencontainers_image.source="https://github.com/ivanprytula/cv-rest-mcp-server" \
      org.opencontainers_image.licenses="Apache-2.0"

ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s CMD wget -qO- http://localhost:$PORT/health || exit 1

CMD ["python", "-m", "services.portfolio.main"]
