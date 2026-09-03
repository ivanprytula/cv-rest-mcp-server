"""Games service entrypoint — Company Culture Bingo (Phase 1b split)."""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import sys
from pathlib import Path
from typing import cast

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.types import ASGIApp

from services.games.routes import router
from services.games.settings import settings
from shared.rate_limiter import limiter


# Cloud Run maps stderr -> ERROR for every line; default logging writes to
# stderr. Send app logs to stdout so WARNING stays WARNING in Logs Explorer.
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Static asset path ──────────────────────────────────────────────────────────
_GAMES_DIR = Path(__file__).parent
_STATIC_DIR = _GAMES_DIR / "static"
_TEMPLATES_DIR = _GAMES_DIR / "templates"


# ── CSP hash computation ───────────────────────────────────────────────────────
def _compute_csp_hashes() -> str:
    """SHA-256 hashes for all inline <script> blocks in games templates."""
    hashes: list[str] = []
    for path in sorted(_TEMPLATES_DIR.rglob("*.html")):
        content = path.read_text(encoding="utf-8")
        for script in re.findall(r"<script>(.*?)</script>", content, re.DOTALL):
            digest = hashlib.sha256(script.encode()).digest()
            hashes.append(f"'sha256-{base64.b64encode(digest).decode()}'")
    return " ".join(hashes)


_CSP_SCRIPT_HASHES = _compute_csp_hashes()

_CSP_DIRECTIVE = (
    f"default-src 'none'; "
    f"script-src 'self' {_CSP_SCRIPT_HASHES}; "
    f"style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
    f"img-src 'self' data:; "
    f"font-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com; "
    f"frame-src 'self'; "
    f"connect-src 'self'"
)


class SecurityHeadersMiddleware:
    """Attach browser-security headers to every HTTP response."""

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


# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="CV REST/MCP Server — Games",
    description="Company Culture Bingo and other interactive games.",
)
app.state.limiter = limiter
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


def _games_rate_limit_handler(request: Request, exc: Exception) -> Response:
    return _rate_limit_exceeded_handler(request, cast(RateLimitExceeded, exc))


app.add_exception_handler(
    RateLimitExceeded,
    _games_rate_limit_handler,
)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)))
app.include_router(router)


@app.get("/health", tags=["Health"])
async def health():
    """Liveness probe for container orchestrators."""
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
