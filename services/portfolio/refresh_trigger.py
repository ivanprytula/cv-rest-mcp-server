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
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from services.portfolio.auth.user_repository import SqlAlchemyUserRepository
from services.portfolio.auth.user_service import (
    UserService,
    resolve_operator_tenant_id,
)
from services.portfolio.db import build_engine, build_session_factory
from services.portfolio.documents.document_repository import (
    SqlAlchemyDocumentRepository,
)
from services.portfolio.documents.document_row import KIND_CV
from services.portfolio.documents.document_service import (
    DocumentService,
    document_sources,
)
from services.portfolio.events.publisher import PostingChanged
from services.portfolio.events.pubsub_publisher import (
    build_event_publisher_from_settings,
)
from services.portfolio.gaps.gap_repository import SqlAlchemyGapRepository
from services.portfolio.gaps.gap_service import GapService, load_analysis_inputs
from services.portfolio.gaps.job_posting_document_store import (
    build_job_posting_document_store_from_settings,
)
from services.portfolio.gaps.tracked_board_repository import (
    SqlAlchemyTrackedBoardRepository,
)
from services.portfolio.gaps.tracked_board_row import API_BACKED_KINDS
from services.portfolio.gaps.tracked_board_service import TrackedBoardService
from services.portfolio.matching.baseline import BaselineError
from services.portfolio.settings import settings
from shared.logging_config import configure_logging
from shared.tracing import TraceContextMiddleware, bind_trace_id


# Structured (JSON-lines) logging — see shared/logging_config.py and the
# equivalent comment in services.portfolio.main. No render pipeline runs
# in this process, so no per-service overrides are needed here.
configure_logging(log_level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # No `upgrade_head` here: migrations are api-core's job (its lifespan
    # already runs them on every deploy). Running them again from a second
    # process risks two processes racing the same DDL for no benefit.
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    # The real publisher, not the default logging fake: this process runs the
    # outbox relay, so it is the one that actually puts events on the queue.
    # Without this the topic, subscription, DLQ and worker are all provisioned
    # and unreachable — nothing would ever be published.
    app.state.gap_service = GapService(
        SqlAlchemyGapRepository(session_factory),
        build_job_posting_document_store_from_settings(),
        build_event_publisher_from_settings(),
    )
    app.state.document_service = DocumentService(
        SqlAlchemyDocumentRepository(session_factory)
    )
    app.state.tracked_board_service = TrackedBoardService(
        SqlAlchemyTrackedBoardRepository(session_factory)
    )
    # Only to resolve which tenant's documents this run reads.
    app.state.user_service = UserService(SqlAlchemyUserRepository(session_factory))
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
app.add_middleware(TraceContextMiddleware)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for Cloud Run."""
    return {"status": "ok"}


@app.post("/trigger")
async def trigger_refresh(group: str | None = None) -> dict[str, object]:
    """Fetch every tracked ATS board, sync postings, and re-analyze changes.

    No request body, no auth check: Cloud Run's platform IAM already
    verified the caller (Scheduler's OIDC token) before this handler runs.
    Returns per-board counts so the Scheduler job's execution log shows
    exactly what happened without a separate query.

    `?group=X` scopes the run to boards tagged with that group — how a
    Cloud Scheduler job with its own cadence polls only its slice of the
    registry (terraform's `ats_refresh_groups` var), and how an operator
    triggers an on-demand batch by hand. Omitted (the scheduled default's
    behavior) means every active API-backed board, regardless of group.
    """
    gap_service: GapService = app.state.gap_service
    documents = app.state.document_service
    tracked_board_service: TrackedBoardService = app.state.tracked_board_service

    # url_only entries have no fetcher and are filtered out here, not inside
    # gap_service.sync_board — that keeps a deliberate url_only board from
    # ever hitting the `fetcher_for(source) is None` branch there, which
    # would otherwise count it as an error on every single refresh run.
    tracked_rows = await tracked_board_service.list_all(active_only=True, group=group)
    boards: list[tuple[str, str]] = [
        (row.kind, row.company_slug)
        for row in tracked_rows
        if row.kind in API_BACKED_KINDS and row.company_slug is not None
    ]
    if not boards:
        logger.info("No ATS boards configured")
        return {"boards": {}}

    # No request, so no token to read a tenant from: this runs for the
    # installation, on the operator's documents.
    tenant_id = await resolve_operator_tenant_id(app.state.user_service)
    if tenant_id is None:
        logger.warning("No operator user; skipping refresh")
        return {"boards": {}}

    try:
        analysis_inputs = await load_analysis_inputs(documents, tenant_id=tenant_id)
    except BaselineError as exc:
        logger.warning("Skipping analysis this run: %s", exc)
        analysis_inputs = None

    live_cv = await documents.read(
        KIND_CV,
        tenant_id=tenant_id,
        fallback_path=document_sources(settings).get(KIND_CV),
    )

    results = await gap_service.refresh_all_boards(
        boards, tenant_id=tenant_id, analysis_inputs=analysis_inputs, live_cv=live_cv
    )
    return {"boards": results}


@app.post("/dispatch-outbox")
async def dispatch_outbox() -> dict[str, int]:
    """Publish pending `event_outbox` rows to Pub/Sub, then prune old ones.

    Lives on this service rather than its own: it reuses the same Cloud
    Scheduler + OIDC + private-ingress setup `/trigger` already has, so it
    needs no new Cloud Run service, service account or IAM binding. No auth
    check here for the same reason as `/trigger` — Cloud Run's platform IAM
    verified the caller before this handler ran.

    Delivery is **at-least-once** by design. A crash between publishing a
    message and stamping `published_at` re-publishes it on the next pass;
    that is correct rather than a gap to close, because the consumer's writes
    are idempotent upserts and it additionally drops stale events by
    `content_hash` (`analysis_worker.handle_posting_changed`). Two-phase
    commit would buy exactly-once at a cost nothing here needs.

    Overlapping runs are safe without a global lock: the claim uses
    `FOR UPDATE SKIP LOCKED`, so a second run takes the next batch instead of
    blocking on or duplicating this one's.
    """
    gap_service: GapService = app.state.gap_service
    repo = gap_service.event_repository
    publisher = gap_service.publisher

    events = await repo.claim_pending_events()
    published_ids: list[int] = []
    for event in events:
        payload = event.payload
        # Adopt the id of the request that recorded this event, so the relay's
        # own log lines for it join that trace rather than this drain's.
        with bind_trace_id(payload.get("trace_id")) as trace_id:
            try:
                await publisher.publish(
                    PostingChanged(
                        posting_id=payload["posting_id"],
                        tenant_id=payload["tenant_id"],
                        status=payload["status"],
                        content_hash=payload["content_hash"],
                        trace_id=trace_id,
                    )
                )
            except Exception:
                # Leave published_at NULL so the next run retries this row. One
                # bad event must not strand the rest of the batch.
                logger.warning(
                    "Failed to publish outbox event %s", event.id, exc_info=True
                )
                continue
            published_ids.append(event.id)

    await repo.mark_events_published(published_ids)
    pruned = await repo.prune_published_events()
    return {
        "claimed": len(events),
        "published": len(published_ids),
        "pruned": pruned,
    }


if __name__ == "__main__":
    # log_config=None: configure_logging() above already applied the
    # structured config at import time — uvicorn's default log_config
    # would otherwise reset the root logger after this point.
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_config=None)
