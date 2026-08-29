"""Bearer-token auth for POST /cv/tailor and tailored-revision reads.

Pure ASGI middleware: scope-scoped to the mutation route plus the
`?tailored=` reads that expose its output, fail-closed when no token is
configured, and constant-time compared via `secrets.compare_digest` to
avoid timing attacks.

Mirrors the shape of `GuardMiddleware` (one class, one job) so future
contributors can read either without learning two patterns. The middleware
is intentionally narrow: it does not gate the public CV surface, and it
does not enforce IP allowlists (the global `GuardMiddleware` already does
that when configured). Adding a new operator-only route is a one-line
change to the predicates below; adding a new auth scheme is a separate
middleware.

Why the tailored reads are protected: `/cv/tailor` is Bearer-gated, so
its output must not be readable over the public surface. The revisions
live in a directory indexed by an unguessable timestamp, but `latest`
is a constant name — guarding `?tailored=` (via Authorization header, or
via `?token=` for the preview page whose browser iframe cannot send
headers) keeps JD-derived content behind the same token.
"""

from __future__ import annotations

import logging
import secrets
from urllib.parse import parse_qs

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.settings import settings


logger = logging.getLogger(__name__)

# The mutation route protected by this middleware. POST is the only
# meaningful verb on /cv/tailor today; the predicate is method-scoped to
# make that explicit.
_PROTECTED_METHOD = "POST"
_PROTECTED_MUTATION_PATH = "/cv/tailor"

# Read routes that expose a tailored revision via ?tailored= (bare
# cv_tailored-*.json filename or "latest"). The whole route stays public
# without a `tailored` parameter — only the revision view is gated.
_TAILORED_READ_METHOD = "GET"
_TAILORED_READ_PATHS = {"/cv/html", "/cv/pdf", "/cv/preview"}

_DIRECT_QUERY_TOKEN = "token"

_BEARER_PREFIX = "bearer "  # case-insensitive per RFC 6750
_WWW_AUTHENTICATE = "Bearer"


def _resolve_token() -> str:
    """Return the configured bearer token, preferring the file form.

    A configured file that cannot be read is a startup error (mirrors
    `ip_lists.load_ip_list`): silently ignoring a missing file would
    disable the policy the operator believes is active.
    """
    inline = settings.tailor_bearer_token.strip()
    path = settings.tailor_bearer_token_file
    if path is not None:
        return path.read_text(encoding="utf-8").strip()
    return inline


def _is_configured() -> bool:
    return bool(
        settings.tailor_bearer_token.strip()
        or settings.tailor_bearer_token_file is not None
    )


def _extract_bearer(headers: list[tuple[bytes, bytes]]) -> tuple[str | None, bool]:
    """Parse the Authorization header for a Bearer token.

    Returns (token, malformed_flag):
    - (None, True): header is missing or does not start with `Bearer `
    - (None, False): header is well-formed but the token is empty
    - (token, False): a non-empty token to compare
    """
    for raw_key, raw_value in headers:
        if raw_key.lower() != b"authorization":
            continue
        try:
            value = raw_value.decode("latin-1")
        except UnicodeDecodeError:
            return None, True
        if not value[: len(_BEARER_PREFIX)].lower() == _BEARER_PREFIX:
            return None, True
        token = value[len(_BEARER_PREFIX) :].strip()
        return (token or None), False
    return None, True


def _query_param(scope: Scope, name: str) -> str:
    """Return the first value of an `name=` query parameter (stripped)."""
    raw = scope.get("query_string", b"")
    params = parse_qs(raw.decode("latin-1", "replace"), keep_blank_values=True)
    values = params.get(name)
    return values[0].strip() if values else ""


def _is_tailored_read(scope: Scope) -> bool:
    """True for the GET routes only when a `tailored` selector is present."""
    if (
        scope.get("method") != _TAILORED_READ_METHOD
        or scope.get("path") not in _TAILORED_READ_PATHS
    ):
        return False
    return bool(_query_param(scope, "tailored"))


def _is_protected(scope: Scope) -> bool:
    if (
        scope.get("method") == _PROTECTED_METHOD
        and scope.get("path") == _PROTECTED_MUTATION_PATH
    ):
        return True
    return _is_tailored_read(scope)


class TailorAuthMiddleware:
    """Bearer-token gate for POST /cv/tailor and ?tailored= revision reads.

    Order of checks (fail-closed at every step):
    1. Scope is not an HTTP request, or the request is not protected
       (not the mutation route, or a CV read without `tailored`) -> pass.
    2. No token configured -> 503 (the endpoints are intentionally off).
    3. Authorization header missing/malformed -> for the GET revision
       reads only, the `?token=` query parameter is accepted as a
       fallback (a preview iframe cannot send headers); otherwise 401.
    4. Token mismatch (constant-time) -> 401 + WWW-Authenticate.
    5. Token matches -> pass through to the route handler.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not _is_protected(scope):
            await self.app(scope, receive, send)
            return

        if not _is_configured():
            logger.warning(
                "Protected tailor endpoint requested but TAILOR_BEARER_TOKEN is "
                "not configured; endpoint is disabled (fail-closed)."
            )
            await self._deny(
                scope,
                receive,
                send,
                503,
                "Tailor endpoint not configured (TAILOR_BEARER_TOKEN missing)",
            )
            return

        try:
            expected = _resolve_token()
        except FileNotFoundError:
            logger.exception(
                "TAILOR_BEARER_TOKEN_FILE points to a missing file; the tailor "
                "endpoints are disabled until the file exists."
            )
            await self._deny(
                scope,
                receive,
                send,
                503,
                "Tailor endpoint not configured (TAILOR_BEARER_TOKEN_FILE missing)",
            )
            return

        if not expected:
            logger.warning(
                "TAILOR_BEARER_TOKEN resolved to an empty value; the tailor "
                "endpoints are disabled (fail-closed)."
            )
            await self._deny(
                scope,
                receive,
                send,
                503,
                "Tailor endpoint not configured (TAILOR_BEARER_TOKEN missing)",
            )
            return

        token, malformed = _extract_bearer(scope.get("headers", []))
        if malformed or token is None:
            # The preview page embeds the revision in an iframe, which cannot
            # set an Authorization header — accept `?token=` for GET reads
            # only. The mutation route is header-only so the secret never
            # leaks into the query string's log footprint.
            if scope.get("method") == _TAILORED_READ_METHOD:
                token = _query_param(scope, _DIRECT_QUERY_TOKEN) or None
                malformed = token is None
        if malformed or token is None:
            await self._deny(
                scope,
                receive,
                send,
                401,
                "Missing or malformed Authorization header",
            )
            return

        # Constant-time compare on UTF-8 bytes. Do NOT pre-check length:
        # compare_digest handles that internally without leaking via the
        # comparison path. The `Authorization` header is consumed; do not
        # log it (the secret must never appear in logs).
        presented = token.encode("utf-8")
        configured = expected.encode("utf-8")
        if not secrets.compare_digest(configured, presented):
            await self._deny(
                scope,
                receive,
                send,
                401,
                "Invalid bearer token",
            )
            return

        await self.app(scope, receive, send)

    async def _deny(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        detail: str,
    ) -> None:
        response = JSONResponse(
            {"detail": detail},
            status_code=status_code,
            headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
        )
        await response(scope, receive, send)
