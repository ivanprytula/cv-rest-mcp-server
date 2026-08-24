import base64
import logging
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

from app.constants import PDF_CACHE_MAX_ENTRIES, PDF_EXECUTOR_MAX_WORKERS, STATIC_DIR
from app.pdf_generator import PdfService, ThemeNotFoundError
from app.rate_limiter import limiter
from app.routes import router
from app.settings import settings


logger = logging.getLogger(__name__)

app = FastAPI(title="CV REST/MCP Server")
app.state.limiter = limiter


def _handle_rate_limit_exceeded(request: Request, exc: Exception) -> Response:
    return _rate_limit_exceeded_handler(request, cast(RateLimitExceeded, exc))


app.add_exception_handler(
    RateLimitExceeded,
    _handle_rate_limit_exceeded,
)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

mcp = FastMCP("cv-mcp-agent")


@mcp.tool
def get_cv() -> dict:
    pdf_service = app.state.pdf_service
    if pdf_service is None:
        raise RuntimeError("PDF service not initialized")
    return pdf_service.cv_data


@mcp.tool
def get_available_themes() -> list[str]:
    pdf_service = app.state.pdf_service
    if pdf_service is None:
        raise RuntimeError("PDF service not initialized")
    return pdf_service.list_themes()


@mcp.tool
async def generate_cv_pdf_tool(theme: str) -> str:
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
        settings.cv_data_path,
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
