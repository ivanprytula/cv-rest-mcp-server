from collections.abc import Callable

from fastapi import Request
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from slowapi.errors import RateLimitExceeded

from app.constants import MCP_PDF_RATE_LIMIT, MCP_READ_RATE_LIMIT
from app.failban import register_violation_from_request
from app.rate_limiter import limits


@limits(MCP_READ_RATE_LIMIT, "240/hour")
def _limit_read(request: Request) -> None:
    return None


@limits(MCP_PDF_RATE_LIMIT, "15/hour")
def _limit_pdf_render(request: Request) -> None:
    return None


def _enforce(limit_check: Callable[[Request], None]) -> None:
    try:
        request = get_http_request()
    except RuntimeError:
        # No HTTP context (in-memory transport, direct calls): nothing to limit.
        return
    try:
        limit_check(request)
    except RateLimitExceeded:
        register_violation_from_request(request)
        raise ToolError("Rate limit exceeded") from None


def enforce_mcp_read_limit() -> None:
    """Per-client limit shared by lightweight MCP read tools."""
    _enforce(_limit_read)


def enforce_mcp_pdf_render_limit() -> None:
    """Per-client limit for CPU-heavy MCP PDF renders."""
    _enforce(_limit_pdf_render)
