import base64
import logging
import sys
from contextlib import asynccontextmanager
from typing import cast

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

from app.constants import PDF_CACHE_MAX_ENTRIES, PDF_EXECUTOR_MAX_WORKERS, STATIC_DIR
from app.cv_source import build_cv_source_from_settings
from app.failban import register_violation_from_request
from app.guard_middleware import GuardMiddleware
from app.mcp_limits import enforce_mcp_pdf_render_limit, enforce_mcp_read_limit
from app.pdf_generator import PdfService, ThemeNotFoundError
from app.rate_limiter import limiter
from app.routes import router
from app.settings import settings


# Cloud Run maps stderr -> ERROR for every line; default logging writes to
# stderr. Send app logs to stdout so WARNING stays WARNING in Logs Explorer.
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

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
        "Render a structured CV as a themed HTML page or a downloadable PDF.\n\n"
        "**REST**\n"
        "- `GET /cv` — raw CV JSON\n"
        "- `GET /cv/html?theme=` — rendered CV page\n"
        "- `GET /cv/preview?theme=` — interactive preview toolbar\n"
        "- `GET /cv/pdf?theme=` — PDF download (rate-limited)\n\n"
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


class SecurityHeadersMiddleware:
    """Attach baseline browser-security headers to every HTTP response.

    X-Frame-Options is SAMEORIGIN because /cv/preview embeds /cv/html in an
    iframe; DENY would break that same-origin frame.
    """

    _HEADERS = (
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"SAMEORIGIN"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
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
app.add_middleware(SecurityHeadersMiddleware)

mcp = FastMCP("cv-rest-mcp-server")


@mcp.tool
def get_cv() -> dict:
    enforce_mcp_read_limit()
    pdf_service = app.state.pdf_service
    if pdf_service is None:
        raise RuntimeError("PDF service not initialized")
    return pdf_service.cv_data


@mcp.tool
def get_available_themes() -> list[str]:
    enforce_mcp_read_limit()
    pdf_service = app.state.pdf_service
    if pdf_service is None:
        raise RuntimeError("PDF service not initialized")
    return pdf_service.list_themes()


@mcp.tool
async def generate_cv_pdf_tool(theme: str) -> str:
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


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
