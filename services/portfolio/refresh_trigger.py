"""Private trigger for the ATS refresh job — a separate Cloud Run service.

Not `services.portfolio.main.app`: this is a second, minimal FastAPI app
with exactly one route, deployed as its own Cloud Run service (same image,
different `command` override — see `terraform/modules/cloud_run_service`)
with `ingress = "internal"` and `allow_unauthenticated = false`.

Why a separate app instead of a route on the public API: Cloud Run enforces
`run.invoker` at the platform layer for free on a *private* service, so
Cloud Scheduler's OIDC token is verified before the request ever reaches
this process — no JWT/OIDC verification code needed here at all. api-core
itself stays `allow_unauthenticated = true` (it must, for the public LB
traffic), so Cloud Run's platform would *not* enforce anything if this route
lived there instead; see the Phase 2b plan's PR4 section for the full
reasoning (docs.cloud.google.com/run/docs/securing/ingress confirms Cloud
Scheduler is already exempt from api-core's own ingress restriction, so this
split exists purely for the auth-verification boundary, not for ingress).
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from services.portfolio.db import build_engine, build_session_factory
from services.portfolio.documents.document_repository import (
    SqlAlchemyDocumentRepository,
)
from services.portfolio.documents.document_row import KIND_CV
from services.portfolio.documents.document_service import (
    DocumentService,
    document_sources,
)
from services.portfolio.gaps.ats import parse_tracked_boards
from services.portfolio.gaps.gap_repository import SqlAlchemyGapRepository
from services.portfolio.gaps.gap_service import GapService, load_analysis_inputs
from services.portfolio.matching.baseline import BaselineError
from services.portfolio.settings import settings


logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # No `upgrade_head` here: migrations are api-core's job (its lifespan
    # already runs them on every deploy). Running them again from a second
    # process risks two processes racing the same DDL for no benefit.
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    app.state.gap_service = GapService(SqlAlchemyGapRepository(session_factory))
    app.state.document_service = DocumentService(
        SqlAlchemyDocumentRepository(session_factory)
    )
    yield
    await engine.dispose()


app = FastAPI(
    title="cv-rest-mcp-server — ATS refresh trigger",
    description="Internal-only. Invoked by Cloud Scheduler via OIDC.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for Cloud Run."""
    return {"status": "ok"}


@app.post("/trigger")
async def trigger_refresh() -> dict[str, object]:
    """Fetch every tracked ATS board, sync postings, and re-analyze changes.

    No request body, no auth check: Cloud Run's platform IAM already
    verified the caller (Scheduler's OIDC token) before this handler runs.
    Returns per-board counts so the Scheduler job's execution log shows
    exactly what happened without a separate query.
    """
    boards = parse_tracked_boards(settings.ats_tracked_boards)
    if not boards:
        logger.info("No ATS boards configured (ATS_TRACKED_BOARDS is empty)")
        return {"boards": {}}

    gap_service: GapService = app.state.gap_service
    documents = app.state.document_service

    try:
        analysis_inputs = await load_analysis_inputs(documents)
    except BaselineError as exc:
        logger.warning("Skipping analysis this run: %s", exc)
        analysis_inputs = None

    live_cv = await documents.read(
        KIND_CV, fallback_path=document_sources(settings).get(KIND_CV)
    )

    results = await gap_service.refresh_all_boards(
        boards, analysis_inputs=analysis_inputs, live_cv=live_cv
    )
    return {"boards": results}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
