from starlette.types import ASGIApp, Receive, Scope, Send

from services.portfolio.settings import settings


class TrustedProxySchemeMiddleware:
    """Fixes an HTTP-vs-HTTPS mixup caused by running behind a load balancer.

    The load balancer talks HTTPS to visitors but plain HTTP to our app, so
    FastAPI thinks every request is HTTP and builds wrong URLs (e.g.
    "http://..." links on the landing page instead of "https://..."). The
    load balancer tells us the real protocol in the X-Forwarded-Proto header;
    this middleware reads it and corrects `scope["scheme"]` so the rest of
    the app sees the truth.

    It only touches the scheme, never `scope["client"]` (the caller's IP) —
    that's a separate trust decision handled elsewhere (rate_limiter.py) and
    left alone on purpose. Only runs when TRUST_PROXY is on, i.e. only in
    real deployments, never in local dev.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and settings.trust_proxy:
            for name, value in scope.get("headers", []):
                if name == b"x-forwarded-proto":
                    proto = value.decode("latin-1").split(",")[0].strip()
                    if proto in {"http", "https"}:
                        scope["scheme"] = proto
                    break

        await self.app(scope, receive, send)
