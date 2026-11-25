import base64
import hashlib
import logging
import re
from contextlib import asynccontextmanager
from typing import Any, cast

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.types import ASGIApp

from services.portfolio.constants import (
    PDF_CACHE_MAX_ENTRIES,
    PDF_EXECUTOR_MAX_WORKERS,
    STATIC_DIR,
    TEMPLATE_DIR,
)

# DB-dependent service imports (commented out for api-core without DB)
# from services.portfolio.cv_extraction import CVExtractionService
# from services.portfolio.cv_review.critic_agent import CVCriticService
# from services.portfolio.cv_review.review_service import CVReviewService
# from services.portfolio.db import build_engine, build_session_factory
# from services.portfolio.db_migrations import upgrade_head
# from services.portfolio.documents.document_repository import (
#     SqlAlchemyDocumentRepository,
# )
# from services.portfolio.documents.document_service import (
#     DocumentService,
#     document_sources,
# )
# from services.portfolio.documents.routes import router as documents_router
# from services.portfolio.events.pubsub_publisher import (
#     build_event_publisher_from_settings,
# )
from services.portfolio.failban import register_violation_from_request

# from services.portfolio.gaps.gap_repository import SqlAlchemyGapRepository
# from services.portfolio.gaps.gap_service import GapService
# from services.portfolio.gaps.idempotency_repository import (
#     SqlAlchemyIdempotencyRepository,
# )
# from services.portfolio.gaps.job_posting_document_store import (
#     build_job_posting_document_store_from_settings,
# )
# from services.portfolio.gaps.routes import postings_router
# from services.portfolio.gaps.routes import router as gaps_router
# from services.portfolio.gaps.tracked_board_repository import (
#     SqlAlchemyTrackedBoardRepository,
# )
# from services.portfolio.gaps.tracked_board_routes import (
#     router as tracked_boards_router,
# )
# from services.portfolio.gaps.tracked_board_service import TrackedBoardService
from services.portfolio.guard_middleware import GuardMiddleware
from services.portfolio.mcp_limits import (
    enforce_mcp_pdf_render_limit,
    enforce_mcp_read_limit,
)
from services.portfolio.pdf_generator import PdfService, ThemeNotFoundError
from services.portfolio.proxy_scheme_middleware import TrustedProxySchemeMiddleware
from services.portfolio.rate_limiter import limiter

# from services.portfolio.revisions.revision_repository import (
#     SqlAlchemyRevisionRepository,
# )
# from services.portfolio.revisions.revision_service import RevisionService
from services.portfolio.routes import router
from services.portfolio.settings import settings

# from services.portfolio.tenancy import verify_rls_enforced
from shared.logging_config import configure_logging
from shared.tracing import TraceContextMiddleware


# Structured (JSON-lines) logging — see shared/logging_config.py. Applied
# here for `python -m services.portfolio.main` (the Dockerfile's
# entrypoint); uvicorn's CLI path (justfile's dev-local) instead passes
# `--log-config shared/logging_config.json` (the same base, minus
# per-service overrides — uvicorn's `--log-config` can't run Python), since
# uvicorn's own default log_config runs after importing the app and would
# otherwise reset the root logger regardless of what this call configures.
# WeasyPrint logs every font-subsetting detail at INFO — muted here, not in
# the shared base, since api-games has no render pipeline to mute.
configure_logging(
    extra_loggers={
        "weasyprint": {"level": "WARNING"},
        "fontTools": {"level": "WARNING"},
    },
    log_level=settings.log_level,
)

logger = logging.getLogger(__name__)


app = FastAPI(
    title="CV REST/MCP Server",
    description=(
        "Render a structured CV as a themed HTML page or a downloadable PDF, "
        "and tailor it to a job description.\n\n"
        "**REST** (full contract + status codes in `docs/api.md`)\n"
        "- `GET /cv` — raw CV JSON\n"
        "- `GET /cv/html?theme=` — rendered CV page\n"
        "- `GET /cv/preview?theme=` — interactive preview toolbar\n"
        "- `GET /cv/pdf?theme=` — PDF download (rate-limited)\n"
        "- `POST /api/v1/cv/tailor` — tailored CV from a JD (Bearer-token protected, "
        "text/Markdown/JSON/PDF/DOCX)\n\n"
        'Errors use `{"detail": ...}`; documented codes: 404, 413, 422, 429, '
        "500, 503.\n\n"
        "**MCP** — mount `/mcp` in any MCP client "
        "(config snippet on the landing page)."
    ),
    swagger_ui_parameters={"persistAuthorization": True},
)
app.state.limiter = limiter


def _handle_rate_limit_exceeded(request: Request, exc: Exception) -> Response:
    register_violation_from_request(request)
    return _rate_limit_exceeded_handler(request, cast(RateLimitExceeded, exc))


app.add_exception_handler(
    RateLimitExceeded,
    _handle_rate_limit_exceeded,
)


def _compute_csp_hashes() -> str:
    """Compute SHA-256 hashes for all inline <script> blocks in templates.

    Hashes are computed at import time from the template files so CSP stays
    in sync with the actual script content.  If a template script changes,
    the browser blocks it until this value is updated — fail-safe by design.
    """
    hashes: list[str] = []
    for path in sorted(TEMPLATE_DIR.rglob("*.html")):
        content = path.read_text(encoding="utf-8")
        for script in re.findall(r"<script>(.*?)</script>", content, re.DOTALL):
            digest = hashlib.sha256(script.encode()).digest()
            hashes.append(f"'sha256-{base64.b64encode(digest).decode()}'")
    return " ".join(hashes)


_CSP_SCRIPT_HASHES = _compute_csp_hashes()

_CSP_DIRECTIVE = (
    f"default-src 'none'; "
    f"script-src 'self' {_CSP_SCRIPT_HASHES} "
    f"'sha256-XTvE4/j+4VrcOi0834D9ftRidsHshjIBrS9hnK4HmY0=' "  # pragma: allowlist secret
    f"https://cdn.jsdelivr.net; "
    f"style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
    f"img-src 'self' data: https://fastapi.tiangolo.com; "
    f"font-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com; "
    f"frame-src 'self'; "
    f"connect-src 'self'"
)


class SecurityHeadersMiddleware:
    """Attach browser-security headers to every HTTP response.

    X-Frame-Options is SAMEORIGIN because /cv/preview embeds /cv/html in an
    iframe; DENY would break that same-origin frame.

    Content-Security-Policy uses per-script SHA-256 hashes so inline scripts
    run without 'unsafe-inline'.  The hashes are computed from template files
    at import time; changing a template script requires updating this module
    (the browser will block the script on hash mismatch — fail-safe).
    """

    _HEADERS = (
        (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"SAMEORIGIN"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (b"content-security-policy", _CSP_DIRECTIVE.encode()),
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                message.setdefault("headers", []).extend(
                    h for h in self._HEADERS if h[0] not in existing
                )
            await send(message)

        await self.app(scope, receive, send_with_headers)


# Middleware runs in reverse addition order: SecurityHeaders then Guard execute
# first, so responses carry headers even when the guard rejects the client.
# TrustedProxyScheme is added LAST (outermost of all) so scope["scheme"] is
# corrected before any other middleware or route handler runs.
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GuardMiddleware)
# Middleware order (Starlette wraps inside-out as we add, but runs
# outside-in on the request): SecurityHeaders is outermost (added last)
# so it stamps CSP etc. on every response, including the 401/403/503 from
# Guard. Guard runs before SecurityHeaders so geo/failban/service-hours
# still apply to the public surface.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(TrustedProxySchemeMiddleware)
# Outermost of all (added last): the correlation id must be bound before any
# other middleware logs, so a guard rejection or a 401 is as attributable as
# a successful request. Safe above TrustedProxyScheme — it only reads a
# header and never touches scope["scheme"].
app.add_middleware(TraceContextMiddleware)

mcp = FastMCP("cv-rest-mcp-server")


@mcp.tool
async def get_cv() -> dict:
    """Return the complete CV as structured JSON data."""
    enforce_mcp_read_limit()
    pdf_service = app.state.pdf_service
    if pdf_service is None:
        raise RuntimeError("PDF service not initialized")
    return await pdf_service.cv_data()


@mcp.tool
def get_available_themes() -> list[str]:
    """Return the names of all themes available for CV rendering."""
    enforce_mcp_read_limit()
    pdf_service = app.state.pdf_service
    if pdf_service is None:
        raise RuntimeError("PDF service not initialized")
    return pdf_service.list_themes()


@mcp.tool
async def generate_cv_pdf_tool(theme: str) -> str:
    """Render the CV with the selected theme and return the PDF as base64 text.

    Args:
        theme: Name of an available CV theme.
    """
    enforce_mcp_pdf_render_limit()
    pdf_service = app.state.pdf_service
    if pdf_service is None:
        raise RuntimeError("PDF service not initialized")
    try:
        pdf_bytes = await pdf_service.generate_cv_pdf_async(theme)
    except ThemeNotFoundError as exc:
        raise ToolError(exc.detail) from exc
    except ToolError:
        raise
    except Exception:
        logger.exception("MCP PDF generation failed for theme '%s'", theme)
        raise ToolError("PDF generation failed") from None
    return base64.b64encode(pdf_bytes).decode("utf-8")


# Unpublished: the JD-matching tool is disabled and no longer listed by
# tools/list. The skill bank's trust policy only keeps atoms the live CV
# already vouches for, so a CV with empty skill sections tailors to an empty
# result — the tool advertised a capability it could not deliver. Re-enable by
# restoring the @mcp.tool decorator below; the implementation and its tests are
# unchanged and still cover the pipeline.
async def match_job_posting(posting_text: str, title: str = "") -> dict:
    """Match a job description against the skill bank and return a tailored version.

    The tailored CV's skills are built from bank atoms whose level meets the
    JD qualifiers and that are already vouched for on the live CV (trust
    policy). Skills carry no qualifier level filtering when the JD states
    none.

    Args:
        posting_text: Full text of the job description.
        title: Optional override for the CV title field.
    """
    enforce_mcp_read_limit()
    pdf_service = app.state.pdf_service
    document_service = app.state.document_service
    operator_tenant_id = app.state.operator_tenant_id
    if pdf_service is None or document_service is None or operator_tenant_id is None:
        raise RuntimeError("PDF service not initialized")
    from services.portfolio.matching.baseline import BaselineError, get_baseline_async
    from services.portfolio.matching.tailor import tailor_cv
    from services.portfolio.matching.taxonomy import build_alias_table

    try:
        baseline_atoms = await get_baseline_async(
            document_service, tenant_id=operator_tenant_id
        )
    except BaselineError as exc:
        logger.warning("Skill bank unavailable: %s", exc)
        raise ToolError("CV tailoring failed") from exc
    try:
        aliases = build_alias_table(baseline_atoms)
        return tailor_cv(
            posting_text,
            baseline_atoms,
            await pdf_service.cv_data(),
            title=title,
            aliases=aliases,
        )
    except Exception:
        logger.exception("MCP JD tailoring failed")
        raise ToolError("CV tailoring failed") from None


mcp_app = mcp.http_app(path="/")


@asynccontextmanager
async def lifespan(app):
    # DB-dependent lifespan (commented out for api-core without DB)
    # One app-wide engine/pool (ADR-023), shared by every repository —
    # NOT one engine per repository (see services.portfolio.db's docstring).
    # Run Alembic migrations up to head, then idempotently seed the first
    # admin. Routes reach services via FastAPI's Depends
    # (dependencies.get_user_service/get_revision_service), same pattern as
    # pdf_service above. Schema is migration-managed, not derived from the
    # current model state via create_all.
    # await upgrade_head(settings.sync_database_url)
    # engine = build_engine(settings.database_url)
    # session_factory = build_session_factory(engine)
    # Migrations connect as the superuser; the app must not. Checked here
    # rather than repaired, because a role that bypasses the tenant policy
    # fails silently — every query succeeds and returns too many rows.
    # await verify_rls_enforced(session_factory)
    #
    # user_repo = SqlAlchemyUserRepository(session_factory)
    # user_service = UserService(user_repo)
    # app.state.user_service = user_service
    # await seed_first_admin_from_settings(user_service)
    #
    # # Revision store: additive (ADR-023 PR4). The tailor route degrades to
    # # the file-glob path on any RevisionService error rather than 500ing.
    # revision_repo = SqlAlchemyRevisionRepository(session_factory)
    # app.state.revision_service = RevisionService(revision_repo)
    #
    # # Refresh-token families (ADR-023 PR5): replaces the in-memory store so
    # # rotation/replay-detection stays correct across restarts and instances.
    # refresh_token_repo = SqlAlchemyRefreshTokenRepository(session_factory)
    # app.state.refresh_token_service = RefreshTokenService(refresh_token_repo)
    #
    # # Gap analysis: stores job postings and ranks what to learn next.
    # # Raw posting text/payload live in Firestore, not
    # # Postgres — gap_repo only ever sees the relational skeleton.
    # gap_repo = SqlAlchemyGapRepository(session_factory)
    # posting_docs = build_job_posting_document_store_from_settings()
    # event_publisher = build_event_publisher_from_settings()
    # app.state.gap_service = GapService(gap_repo, posting_docs, event_publisher)
    #
    # # Retry-safety for POST /api/v1/postings. Only that route needs it today,
    # # so it stays a repository on app.state rather than a shared dependency
    # # across every POST — the others are admin-only or already upsert-idempotent.
    # app.state.idempotency_repository = SqlAlchemyIdempotencyRepository(session_factory)
    #
    # # Tracked-board registry: what the ATS refresh trigger polls. Independent
    # # of AtsBoardRow (gap_repo's fetch-cache) — this is the operator-editable
    # # "what to track" list, not fetch state.
    # tracked_board_repo = SqlAlchemyTrackedBoardRepository(session_factory)
    # app.state.tracked_board_service = TrackedBoardService(tracked_board_repo)
    #
    # # Operator documents (live CV, skill bank, JD vocabulary) in Postgres.
    # # Seeding is idempotent — an existing row is never overwritten, so a
    # # redeploy cannot clobber edits made through the API. Reads fall back to
    # # the JSON files, so local dev works with no database at all.
    # document_service = DocumentService(SqlAlchemyDocumentRepository(session_factory))
    # app.state.document_service = document_service
    # # Seeds into the operator's tenant, so the shipped JSON becomes their
    # # documents rather than belonging to nobody. Skipped when no operator
    # # exists yet (no FIRST_ADMIN_PASSWORD configured): the files still serve
    # # every read through the fallback, and the next boot seeds them.
    # operator_tenant_id = await resolve_operator_tenant_id(user_service)
    # app.state.operator_tenant_id = operator_tenant_id
    # if operator_tenant_id is not None:
    #     await document_service.seed_from_files(
    #         document_sources(settings), tenant_id=operator_tenant_id
    #     )

    # File-based CV source for api-core (portfolio) without DB dependency.
    # Uses the local cv.json file directly via a minimal DocumentService that
    # reads from the fallback path (data/cv.json).
    import json
    from pathlib import Path

    from services.portfolio.documents.document_row import KIND_CV
    from services.portfolio.documents.document_service import DocumentService
    from services.portfolio.settings import settings as portfolio_settings
    from services.portfolio.tenancy import TenantId

    class FileOnlyDocumentRepository:
        """Minimal document repository that reads only from local files."""

        def __init__(self, cv_data_path: Path) -> None:
            self._cv_data_path = cv_data_path

        async def get(self, kind: str, *, tenant_id: int) -> Any:
            if kind == KIND_CV:
                try:
                    return {
                        "payload": json.loads(
                            self._cv_data_path.read_text(encoding="utf-8")
                        )
                    }
                except OSError, json.JSONDecodeError:
                    return None
            return None

        async def put(
            self, *, kind: str, payload: dict[str, Any], tenant_id: int
        ) -> Any:
            return None

        async def list_all(self, *, tenant_id: int) -> list[Any]:
            return []

        async def delete(self, kind: str, *, tenant_id: int) -> bool:
            return False

        async def list_kinds(self, *, tenant_id: int) -> list[str]:
            return [KIND_CV]

    # Create a minimal document service that reads from the local cv.json file
    cv_data_path = portfolio_settings.cv_data_path
    file_repo = FileOnlyDocumentRepository(cv_data_path)
    document_service = DocumentService(file_repo)

    # Use a dummy tenant_id (0) since we're not using multi-tenancy
    dummy_tenant_id = TenantId(0)

    pdf_service = PdfService(
        document_service,
        dummy_tenant_id,
        max_entries=PDF_CACHE_MAX_ENTRIES,
        max_workers=PDF_EXECUTOR_MAX_WORKERS,
    )
    app.state.pdf_service = pdf_service

    # CV-intake extraction (Phase 3b): optional, unlike every service above.
    # No API key means the feature is off, not a startup failure — nothing
    # else in this app depends on it.
    # DB-dependent services (commented out for api-core without DB)
    # if settings.anthropic_api_key:
    #     import anthropic
    #     anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    #     app.state.cv_extraction_service = CVExtractionService(anthropic_client)
    #     # CV-review critique (Phase 3f.5): a second call over the same
    #     # client, extractor + critic composed behind one A2A-shaped
    #     # orchestration — see services/portfolio/cv_review/review_service.py.
    #     app.state.cv_review_service = CVReviewService(
    #         app.state.cv_extraction_service, CVCriticService(anthropic_client)
    #     )

    async with mcp_app.lifespan(app):
        yield

    # await engine.dispose()
    if pdf_service is not None:
        pdf_service._executor.shutdown(wait=False)


app.router.lifespan_context = lifespan
app.mount("/mcp", mcp_app)
app.mount("/static", StaticFiles(directory=STATIC_DIR))
app.include_router(router)
# DB-dependent routers (commented out for api-core without DB)
# app.include_router(gaps_router)
# app.include_router(postings_router)
# app.include_router(documents_router)
# app.include_router(tracked_boards_router)


if __name__ == "__main__":
    # log_config=None: configure_logging() above already applied the
    # structured config at import time — uvicorn's default log_config
    # would otherwise reset the root logger after this point.
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_config=None)
