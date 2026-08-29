import base64
import hashlib
import logging
import re
import sys
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

from app.constants import (
    PDF_CACHE_MAX_ENTRIES,
    PDF_EXECUTOR_MAX_WORKERS,
    STATIC_DIR,
    TEMPLATE_DIR,
)
from app.cv_source import build_cv_source_from_settings
from app.failban import register_violation_from_request
from app.guard_middleware import GuardMiddleware
from app.mcp_limits import enforce_mcp_pdf_render_limit, enforce_mcp_read_limit
from app.pdf_generator import PdfService, ThemeNotFoundError
from app.rate_limiter import limiter
from app.routes import router
from app.settings import settings
from app.tailor_auth import TailorAuthMiddleware


# Cloud Run maps stderr -> ERROR for every line; default logging writes to
# stderr. Send app logs to stdout so WARNING stays WARNING in Logs Explorer.
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

# Third-party render pipeline logs every font-subsetting detail at INFO;
# keep root at INFO for app messages (cv_source reloads) but silence these.
for _noisy in ("weasyprint", "fontTools"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def _openapi_contact() -> dict[str, str] | None:
    contact = {}
    if settings.contact_name:
        contact["name"] = settings.contact_name
    if settings.contact_email:
        contact["email"] = settings.contact_email
    return contact or None


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
        "- `POST /cv/tailor` — tailored CV from a JD (Bearer-token protected, "
        "text/Markdown/JSON/PDF/DOCX)\n"
        "- `GET /api/games/culture-bingo/content` — bingo tiles JSON\n\n"
        'Errors use `{"detail": ...}`; documented codes: 404, 413, 422, 429, '
        "500, 503.\n\n"
        "**MCP** — mount `/mcp` in any MCP client "
        "(config snippet on the landing page)."
    ),
    contact=_openapi_contact(),
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
    f"'sha256-QOOQu4W1oxGqd2nbXbxiA1Di6OHQOLQD+o+G9oWL8YY=' "
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
# so it stamps CSP etc. on every response, including the 401/503 from
# TailorAuth. Guard runs before TailorAuth so geo/failban/service-hours
# still apply to /cv/tailor, and failban can ban a client before we even
# bother checking the bearer token. TailorAuth short-circuits on the
# protected path/method; everything else passes through untouched.
app.add_middleware(TailorAuthMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

mcp = FastMCP("cv-rest-mcp-server")


@mcp.tool
def get_cv() -> dict:
    """Return the complete CV as structured JSON data."""
    enforce_mcp_read_limit()
    pdf_service = app.state.pdf_service
    if pdf_service is None:
        raise RuntimeError("PDF service not initialized")
    return pdf_service.cv_data


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


@mcp.tool
def match_jd(jd_text: str, title: str = "") -> dict:
    """Match a job description against the skill bank and return a tailored version.

    The tailored CV's skills are built from bank atoms whose level meets the
    JD qualifiers and that are already vouched for on the live CV (trust
    policy). Skills carry no qualifier level filtering when the JD states
    none.

    Args:
        jd_text: Full text of the job description.
        title: Optional override for the CV title field.
    """
    enforce_mcp_read_limit()
    pdf_service = app.state.pdf_service
    if pdf_service is None:
        raise RuntimeError("PDF service not initialized")
    from app.matching.baseline import BaselineError, get_baseline
    from app.matching.tailor import tailor_cv

    try:
        baseline_atoms = get_baseline()
    except BaselineError as exc:
        logger.warning("Skill bank unavailable: %s", exc)
        raise ToolError("CV tailoring failed") from exc
    try:
        return tailor_cv(jd_text, baseline_atoms, pdf_service.cv_data, title=title)
    except Exception:
        logger.exception("MCP JD tailoring failed")
        raise ToolError("CV tailoring failed") from None


mcp_app = mcp.http_app(path="/")


@asynccontextmanager
async def lifespan(app):
    pdf_service = PdfService(
        build_cv_source_from_settings(),
        max_entries=PDF_CACHE_MAX_ENTRIES,
        max_workers=PDF_EXECUTOR_MAX_WORKERS,
    )
    app.state.pdf_service = pdf_service

    async with mcp_app.lifespan(app):
        yield

    pdf_service._executor.shutdown(wait=False)


app.router.lifespan_context = lifespan
app.mount("/mcp", mcp_app)
app.mount("/static", StaticFiles(directory=STATIC_DIR))
app.include_router(router)


# The /cv/tailor endpoint reads the raw body itself (multi-format: JSON,
# PDF, DOCX, text, Markdown) so it declares no FastAPI body parameter —
# FastAPI would otherwise validate any declared param against Content-Type
# and reject e.g. JSON bodies before the handler runs. Swagger/OpenAPI
# still needs a requestBody, so we document it here post-generation.
_TAILOR_REQUEST_BODY = {
    "required": True,
    "description": (
        "Job description in any supported format (max 10 MB): raw text, "
        'Markdown, JSON ({"jd_text": ..., "title": ...}), PDF, or DOCX. '
        "For PDF/DOCX set Content-Type accordingly and send the binary body; "
        "anything else is read as plain text."
    ),
    "content": {
        "text/plain": {
            "schema": {"type": "string"},
            "examples": {
                "raw text": {
                    "summary": "Pasted JD",
                    "value": "Required: Python, FastAPI, PostgreSQL\nWork at EPC Network...",
                },
                "json": {
                    "summary": "JSON payload",
                    "value": '{"jd_text": "Required: Python, FastAPI", "title": ""}',
                },
                "markdown": {
                    "summary": "Markdown JD",
                    "value": "# The Role\n\nWe need **Python** engineers...",
                },
            },
        },
        "application/json": {"schema": {"type": "object"}},
        "application/pdf": {"schema": {"type": "string", "format": "binary"}},
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
            "schema": {"type": "string", "format": "binary"}
        },
    },
}

_openapi_getter = app.openapi

# The /cv/tailor route and the `?tailored=` revision reads are Bearer-token
# gated by TailorAuthMiddleware (ADR-018); Swagger UI needs the security
# scheme declared on those operations so the Authorize button sends
# `Authorization: Bearer <token>`. The reads are only protected WHEN a
# `tailored` selector is present — extra auth headers on the public surface
# are harmless, so the declaration is unconditional here.
_TAILOR_SECURITY_SCHEME = {"type": "http", "scheme": "bearer"}
_TAILOR_SECURE_OPERATIONS = {
    ("/cv/tailor", "post"),
    ("/cv/html", "get"),
    ("/cv/preview", "get"),
    ("/cv/pdf", "get"),
}


def _openapi_with_tailor_contract() -> dict[str, Any]:
    schema = _openapi_getter()
    for path, method in _TAILOR_SECURE_OPERATIONS:
        operation = schema.get("paths", {}).get(path, {}).get(method)
        if operation is None:
            continue
        operation["security"] = [{"HTTPBearer": []}]
        if path == "/cv/tailor" and "requestBody" not in operation:
            operation["requestBody"] = _TAILOR_REQUEST_BODY
    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes.setdefault("HTTPBearer", _TAILOR_SECURITY_SCHEME)
    return schema


app.openapi = cast(Any, _openapi_with_tailor_contract)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
