"""JWT auth middleware for the private surface (Phase 1c/1d, ADR-022).

Pure ASGI, one class, one job: verify a JWT access token on protected
requests, fail-closed. It gates two families of routes:

1. The `/api/v1/*` namespace — any valid JWT (no scope requirement). The
   login/refresh/logout endpoints are the exception: they issue/consume
   credentials, so they are not gated here.
2. The tailoring surface, migrated from `TailorAuthMiddleware` (ADR-018) to the
   same JWT flow:
   - `POST /cv/tailor` — requires a JWT for an **admin-role** user (the `role`
     claim), presented ONLY via the Authorization header (the secret never goes
     in a URL/log).
   - `GET /cv/html|pdf|preview` WITH a `?tailored=` selector — requires a JWT
     with the `cv:read` scope, via Authorization header, or via `?token=` for
     the preview page whose embedded iframe cannot send a header.
   - `GET /api/v1/revisions` — requires a JWT with the `cv:read` scope (same
     as the tailored reads); lists the tailored CV revisions on disk for the
     SPA's revisions screen.

The tailor mutation is gated on the JWT `role` claim (`admin`); the revision
reads stay gated on the `cv:read` scope (both roles have it). A JWT is verified
for signature/exp/iss/aud first, then the required role/scope. All failures
are fail-closed: no signing key -> 503, missing/invalid token -> 401, wrong
role/scope -> 403.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth.crypto import AuthUnconfiguredError, verify_access_token
from app.settings import settings


logger = logging.getLogger(__name__)

# /api/v1/* surface this middleware protects. Paths that issue credentials
# (login/refresh) or only consume them via the cookie (logout) explicitly fall
# through so they can run unauthenticated — they carry their own auth material
# (password / httpOnly refresh cookie), not a bearer access token.
_API_PREFIX = "/api/v1"
_TOKEN_PATH = "/api/v1/auth/token"
_REFRESH_PATH = "/api/v1/auth/refresh"
_LOGOUT_PATH = "/api/v1/auth/logout"

# Tailoring surface (migrated from TailorAuthMiddleware). The mutation route is
# header-only; the revision reads accept `?token=` because the preview page's
# iframe cannot send an Authorization header.
_TAILOR_MUTATION_METHOD = "POST"
_TAILOR_MUTATION_PATH = "/cv/tailor"
_TAILORED_READ_METHOD = "GET"
_TAILORED_READ_PATHS = {"/cv/html", "/cv/pdf", "/cv/preview"}

_REVISIONS_LIST_METHOD = "GET"
_REVISIONS_LIST_PATH = "/api/v1/revisions"

_SCOPE_READ = "cv:read"

_ROLE_ADMIN = "admin"

_DIRECT_QUERY_TOKEN = "token"

_BEARER_PREFIX = "bearer "  # case-insensitive per RFC 6750
_WWW_AUTHENTICATE = "Bearer"


def _is_tailored_read(scope: Scope) -> bool:
    """True for the GET routes only when a `tailored` selector is present."""
    if (
        scope.get("method") != _TAILORED_READ_METHOD
        or scope.get("path") not in _TAILORED_READ_PATHS
    ):
        return False
    return bool(_query_param(scope, "tailored"))


def _query_param(scope: Scope, name: str) -> str:
    """Return the first value of an `name=` query parameter (stripped)."""
    raw = scope.get("query_string", b"")
    params = parse_qs(raw.decode("latin-1", "replace"), keep_blank_values=True)
    values = params.get(name)
    return values[0].strip() if values else ""


def _is_protected(scope: Scope) -> bool:
    """True when the request must carry a verified JWT.

    The public CV surface (`/`, `/cv*` without a `tailored` selector, `/health`,
    `/mcp`) is never protected here. A CORS preflight (OPTIONS) never carries
    credentials — browsers refuse to attach Authorization to it — so it must
    fall through to CORSMiddleware, not be denied here (the SPA's cross-origin
    Authorization-bearing calls would never get past preflight otherwise).
    """
    path = scope.get("path", "")
    method = scope.get("method", "")
    if method == "OPTIONS":
        return False
    if path.startswith(_API_PREFIX):
        return path not in {_TOKEN_PATH, _REFRESH_PATH, _LOGOUT_PATH}
    if method == _TAILOR_MUTATION_METHOD and path == _TAILOR_MUTATION_PATH:
        return True
    return _is_tailored_read(scope)


def _has_scope(claims: dict, required: str | None) -> bool:
    """True if `claims` carries the required scope (None means authenticated only)."""
    if required is None:
        return bool(claims)
    return required in (claims.get("scope") or "").split()


def _has_role(claims: dict, required: str) -> bool:
    """True if `claims` carries the required role."""
    return claims.get("role") == required


def _extract_bearer(headers: list[tuple[bytes, bytes]]) -> tuple[str | None, bool]:
    """Return (token, malformed_flag)."""
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


class JWTAuthMiddleware:
    """Verify a JWT access token on protected requests (API + tailoring).

    Order of checks (fail-closed at every step):
    1. Non-HTTP scope, or a request not protected by this middleware ->
       pass through.
    2. Auth not configured (no signing key) -> 503.
    3. Missing/malformed token -> for GET revision reads only, the `?token=`
       query parameter is accepted as a fallback (an iframe cannot send a
       header); otherwise 401.
    4. Token fails signature/exp/iss/aud verification -> 401.
    5. Token lacks the required scope -> 403.
    6. Verified -> inject decoded claims into `scope["auth"]` and continue.
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

        token, malformed = _extract_bearer(scope.get("headers", []))
        is_read = _is_tailored_read(scope)
        if malformed or token is None:
            # The preview page embeds the revision in an iframe, which cannot
            # set an Authorization header — accept `?token=` for GET reads
            # only. The mutation route and /api/v1/* are header-only so the
            # JWT never leaks into the query string's log footprint.
            if is_read:
                token = _query_param(scope, _DIRECT_QUERY_TOKEN) or None
                malformed = token is None
        if malformed or token is None:
            await self._deny(
                scope, receive, send, 401, "Missing or malformed Authorization header"
            )
            return

        try:
            claims = verify_access_token(token)
        except AuthUnconfiguredError as exc:
            logger.warning("JWT auth requested but signing key not configured: %s", exc)
            await self._deny(
                scope,
                receive,
                send,
                503,
                "Auth not configured (JWT_SIGNING_KEY missing)",
            )
            return
        except Exception:
            # InvalidTokenError (and subclasses) for bad signature/exp/iss/aud,
            # plus any decode failure. Never leak why.
            await self._deny(scope, receive, send, 401, "Invalid or expired token")
            return

        required_scope = self._required_scope(scope)
        if required_scope is not None and not _has_scope(claims, required_scope):
            await self._deny(scope, receive, send, 403, "Insufficient scope")
            return
        if self._requires_admin(scope) and not _has_role(claims, _ROLE_ADMIN):
            await self._deny(scope, receive, send, 403, "Admin role required")
            return

        scope["auth"] = claims
        await self.app(scope, receive, send)

    @staticmethod
    def _is_tailor_mutation(scope: Scope) -> bool:
        return (
            scope.get("method") == _TAILOR_MUTATION_METHOD
            and scope.get("path") == _TAILOR_MUTATION_PATH
        )

    @staticmethod
    def _requires_admin(scope: Scope) -> bool:
        return JWTAuthMiddleware._is_tailor_mutation(scope)

    @staticmethod
    def _is_revisions_list(scope: Scope) -> bool:
        return (
            scope.get("method") == _REVISIONS_LIST_METHOD
            and scope.get("path") == _REVISIONS_LIST_PATH
        )

    @staticmethod
    def _required_scope(scope: Scope) -> str | None:
        if JWTAuthMiddleware._requires_admin(scope):
            return None  # role-gated, not scope-gated
        if _is_tailored_read(scope) or JWTAuthMiddleware._is_revisions_list(scope):
            return _SCOPE_READ
        return None  # /api/v1/* — authenticated only

    @staticmethod
    async def _deny(
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


class CredentialedCORSMiddleware:
    """Pinned-origin CORS for the credential-issuing/consuming endpoints.

    The public surface uses a wildcard, credential-less CORSMiddleware. Login,
    refresh, and logout are the deliberate exceptions: each sets or reads the
    SameSite=None `__Host-refresh_token` cookie cross-origin, so each needs
    `Access-Control-Allow-Credentials: true` with an exact, allow-listed origin
    — never `*` with credentials (login/logout would otherwise silently fail
    to set/revoke the cookie from the SPA's origin).

    This middleware adds the credentialed CORS headers ONLY for OPTIONS
    (preflight) and the actual request on these three paths; everything else
    passes through untouched so the wildcard middleware still owns the public
    surface.
    """

    _CREDENTIALED_PATHS = {_TOKEN_PATH, _REFRESH_PATH, _LOGOUT_PATH}

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")
        is_credentialed = path in self._CREDENTIALED_PATHS
        is_preflight = method == "OPTIONS"

        if not is_credentialed:
            await self.app(scope, receive, send)
            return

        origin = _request_origin(scope)
        allowed = settings.cors_origin.strip()

        if is_preflight:
            # Handle the preflight ourselves so we never fall through to the
            # wildcard CORS (which would respond with `*` — invalid with
            # credentials). Respond 204 with the pinned origin (no body).
            from starlette.responses import Response

            response = Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": allowed,
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Max-Age": "600",
                    "Vary": "Origin",
                },
            )
            await response(scope, receive, send)
            return

        # Actual login/refresh/logout request: stamp the credentialed headers on the start
        # message, OVERRIDING any `Access-Control-Allow-Origin: *` the inner
        # wildcard CORSMiddleware added (credentials with `*` is invalid per
        # spec). If no origin is configured, or the request origin does not
        # match the pinned one, do not add credentialed headers (fail safe).
        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                if origin == allowed and allowed:
                    # Strip the wildcard origin the inner CORS layer added, then
                    # add the pinned origin + credentials.
                    headers = [
                        (k, v)
                        for k, v in headers
                        if k.lower()
                        not in {
                            b"access-control-allow-origin",
                            b"access-control-allow-credentials",
                        }
                    ]
                    headers.extend(
                        [
                            (b"access-control-allow-origin", allowed.encode()),
                            (b"access-control-allow-credentials", b"true"),
                            (b"vary", b"Origin"),
                        ]
                    )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _request_origin(scope: Scope) -> str:
    for raw_key, raw_value in scope.get("headers", []):
        if raw_key.lower() == b"origin":
            return raw_value.decode("latin-1", "replace")
    return ""
