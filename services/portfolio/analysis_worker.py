"""Pub/Sub push subscriber for `PostingChanged` — a separate Cloud Run service.

Not `services.portfolio.main.app`: mirrors `refresh_trigger.py` exactly — a
second, minimal FastAPI app with one route, deployed as its own Cloud Run
service (same image, different `command` override), `ingress = "internal"`
and `allow_unauthenticated = false`. Cloud Run enforces `run.invoker` at the
platform layer for a private service, so the Pub/Sub push subscription's
OIDC token is verified before the request reaches this process — the same
auth-boundary argument as `refresh_trigger.py`'s docstring, just with
Pub/Sub push instead of Cloud Scheduler as the OIDC-bearing caller.

No hand-rolled retry: a non-2xx response nacks the message, and the
subscription's own retry policy + dead-letter topic (`terraform/modules/
pubsub`) handle redelivery and eventual give-up. This process only ever
tries once per delivery.
"""

from __future__ import annotations

import base64
import json
import logging
import sys
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from services.portfolio.db import build_engine, build_session_factory
from services.portfolio.documents.document_repository import (
    SqlAlchemyDocumentRepository,
)
from services.portfolio.documents.document_row import KIND_CV
from services.portfolio.documents.document_service import (
    DocumentService,
    document_sources,
)
from services.portfolio.gaps.gap_repository import SqlAlchemyGapRepository
from services.portfolio.gaps.gap_service import GapService, load_analysis_inputs
from services.portfolio.gaps.job_posting_document_store import (
    build_job_posting_document_store_from_settings,
)
from services.portfolio.matching.baseline import BaselineError
from services.portfolio.settings import settings
from services.portfolio.tenancy import TenantId


logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # No `upgrade_head` here, same reasoning as refresh_trigger.py: api-core's
    # lifespan already runs migrations on every deploy.
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    app.state.gap_service = GapService(
        SqlAlchemyGapRepository(session_factory),
        build_job_posting_document_store_from_settings(),
    )
    app.state.document_service = DocumentService(
        SqlAlchemyDocumentRepository(session_factory)
    )
    yield
    await engine.dispose()


app = FastAPI(
    title="cv-rest-mcp-server — analysis worker",
    description="Internal-only. Invoked by a Pub/Sub push subscription.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for Cloud Run."""
    return {"status": "ok"}


def _decode_push_envelope(body: dict[str, Any]) -> dict[str, Any]:
    """Unwrap a Pub/Sub push envelope's base64 message body to its JSON payload.

    Raises `HTTPException(400)` on anything malformed — a push subscription
    retries a non-2xx response, but a malformed envelope will never become
    well-formed on redelivery, so this is really "give up immediately and
    let the DLQ take it" dressed as a 400.
    """
    try:
        data = body["message"]["data"]
        return json.loads(base64.b64decode(data))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Malformed push envelope") from exc


@app.post("/pubsub/posting-changed")
async def handle_posting_changed(request: Request) -> dict[str, str]:
    """Analyze and cluster the posting named by a `PostingChanged` event.

    No auth check: Cloud Run's platform IAM already verified the caller
    (the push subscription's OIDC token) before this handler runs, same as
    `refresh_trigger.py`'s `/trigger`.
    """
    payload = _decode_push_envelope(await request.json())
    posting_id = payload["posting_id"]
    tenant_id = TenantId(payload["tenant_id"])

    gap_service: GapService = app.state.gap_service
    documents = app.state.document_service

    try:
        analysis_inputs = await load_analysis_inputs(documents, tenant_id=tenant_id)
    except BaselineError as exc:
        logger.warning("Skipping analysis for posting %s: %s", posting_id, exc)
        return {"status": "skipped"}

    live_cv = await documents.read(
        KIND_CV,
        tenant_id=tenant_id,
        fallback_path=document_sources(settings).get(KIND_CV),
    )
    bank, deferred, vocabulary, aliases = analysis_inputs
    await gap_service.analyze_posting(
        posting_id,
        tenant_id=tenant_id,
        bank_atoms=bank,
        deferred_atoms=deferred,
        vocabulary=vocabulary,
        live_cv=live_cv or {},
        aliases=aliases,
    )
    await gap_service.cluster_posting(posting_id, tenant_id=tenant_id)
    return {"status": "processed"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
