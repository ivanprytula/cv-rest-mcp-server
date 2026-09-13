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
from shared.logging_config import configure_logging
from shared.tracing import TraceContextMiddleware


# Structured (JSON-lines) logging — see shared/logging_config.py and the
# equivalent comment in services.portfolio.main. No render pipeline runs
# in this process, so no per-service overrides are needed here.
configure_logging(log_level=settings.log_level)
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
app.add_middleware(TraceContextMiddleware)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for Cloud Run."""
    return {"status": "ok"}


def _decode_push_envelope(
    body: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Unwrap a Pub/Sub push envelope to its JSON payload and its attributes.

    Raises `HTTPException(400)` on anything malformed — a push subscription
    retries a non-2xx response, but a malformed envelope will never become
    well-formed on redelivery, so this is really "give up immediately and
    let the DLQ take it" dressed as a 400.

    Attributes come back alongside the payload because the publisher puts the
    originating request's correlation id there; missing attributes are a
    normal envelope, not an error.
    """
    try:
        message = body["message"]
        payload = json.loads(base64.b64decode(message["data"]))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Malformed push envelope") from exc
    return payload, message.get("attributes") or {}


@app.post("/pubsub/posting-changed")
async def handle_posting_changed(request: Request) -> dict[str, str]:
    """Analyze and cluster the posting named by a `PostingChanged` event.

    No auth check: Cloud Run's platform IAM already verified the caller
    (the push subscription's OIDC token) before this handler runs, same as
    `refresh_trigger.py`'s `/trigger`.
    """
    payload, attributes = _decode_push_envelope(await request.json())
    posting_id = payload["posting_id"]
    tenant_id = TenantId(payload["tenant_id"])

    # Two ids, deliberately both: Cloud Run stamped this push request with its
    # own trace, while the attribute carries the request that changed the
    # posting in the first place. Logging only one would either lose this
    # service's local trace or break the chain back to the originator.
    origin_trace_id = attributes.get("trace_id", "")
    if origin_trace_id:
        logger.info(
            "posting_changed received",
            extra={"origin_trace_id": origin_trace_id},
        )

    gap_service: GapService = app.state.gap_service
    documents = app.state.document_service

    # Delivery from the outbox relay is at-least-once and unordered, so an
    # old event can arrive after a newer one has already been processed.
    # Analyzing it would overwrite the newer analysis with a stale one. 200,
    # not an error: the message is genuinely done with: retrying it would
    # never make it fresh, and a non-2xx would loop it to the DLQ.
    event_hash = payload.get("content_hash")
    posting = await gap_service.get_posting(posting_id, tenant_id=tenant_id)
    if posting is not None and event_hash and posting.content_hash != event_hash:
        logger.info(
            "Skipping stale posting_changed for %s: event %s, stored %s",
            posting_id,
            event_hash,
            posting.content_hash,
        )
        return {"status": "stale"}

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
    # log_config=None: configure_logging() above already applied the
    # structured config at import time — uvicorn's default log_config
    # would otherwise reset the root logger after this point.
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_config=None)
