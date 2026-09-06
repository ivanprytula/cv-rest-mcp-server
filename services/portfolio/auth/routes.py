"""Auth endpoints: token (login), refresh, logout, me.

Router prefix `/api/v1/auth`. The login and refresh endpoints are excluded from
`JWTAuthMiddleware` so they can run unauthenticated; `me` is protected and reads
the verified claims injected into `scope["auth"]` by the middleware.

Credential transport (ADR-022): the access token is returned in the JSON body
and kept memory-only by the SPA. The refresh token is delivered as an httpOnly
cookie scoped to this router so it never touches JavaScript storage. In
production it is `__Host-refresh_token`, Secure, SameSite=None (required for
the cross-origin app.<apex> -> api.<apex> call). In dev it is an unprefixed
`refresh_token`, no Secure, SameSite=Lax — plain-HTTP localhost can satisfy
neither the `__Host-` prefix's HTTPS requirement (enforced by Firefox/Safari
even with Secure absent) nor SameSite=None's Secure requirement, so dev uses
the weaker-but-functional cookie shape instead of one browsers silently drop.
Only the refresh endpoint accepts credentials cross-origin via
`CredentialedCORSMiddleware`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from services.portfolio.auth.crypto import (
    AuthUnconfiguredError,
    generate_refresh_token,
    hash_refresh_token,
    sign_access_token,
)
from services.portfolio.auth.refresh_token_service import RefreshTokenService
from services.portfolio.auth.user import ROLE_USER
from services.portfolio.auth.user_service import UserService
from services.portfolio.constants import API_V1_PREFIX
from services.portfolio.dependencies import (
    get_refresh_token_service,
    get_user_service,
)
from services.portfolio.schemas.auth import LoginRequest, MeResponse, TokenPair
from services.portfolio.settings import settings


auth_router = APIRouter(prefix=f"{API_V1_PREFIX}/auth", tags=["auth"])

get_user_service_dep = Depends(get_user_service)
get_refresh_token_service_dep = Depends(get_refresh_token_service)

# The __Host- prefix REQUIRES Path=/, Secure, no Domain, AND (per Firefox and
# Safari, unlike Chrome which special-cases localhost) an actual HTTPS
# connection — not just the Secure attribute. Local dev's plain-HTTP uvicorn
# can never satisfy that, so the prefix itself — not just Secure/SameSite —
# is production-only; dev uses an unprefixed cookie name instead.
# Because Path=/ the cookie is sent on every request, but it is httpOnly so JS
# never sees it and only the server-side refresh/logout endpoints consume it.
# SameSite=None + Secure allows the credentialed cross-origin call from
# app.<apex> to api.<apex>.
_COOKIE_PATH = "/"


def _refresh_cookie_name() -> str:
    return (
        "__Host-refresh_token"
        if settings.environment == "production"
        else "refresh_token"
    )


def _refresh_ttl_seconds() -> int:
    return settings.refresh_token_ttl_days * 86400


def _set_refresh_cookie(response: Response, token: str) -> None:
    # In local dev over HTTP, Secure=True rejects the cookie, so Secure (and
    # SameSite=None, which REQUIRES Secure per spec — browsers silently drop
    # the whole Set-Cookie otherwise) are both production-only. Dev's SPA and
    # API differ only by port (localhost:5173 -> :8080), which is still
    # same-site, so SameSite=Lax still lets the cookie through.
    is_production = settings.environment == "production"
    response.set_cookie(
        key=_refresh_cookie_name(),
        value=token,
        max_age=_refresh_ttl_seconds(),
        path=_COOKIE_PATH,
        secure=is_production,
        httponly=True,
        samesite="none" if is_production else "lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=_refresh_cookie_name(), path=_COOKIE_PATH)


def _read_refresh_cookie(request: Request) -> str | None:
    return request.cookies.get(_refresh_cookie_name())


def _get_auth_claims(request: Request) -> dict:
    """Return verified JWT claims injected by JWTAuthMiddleware."""
    claims = request.scope.get("auth")
    if claims is None:
        raise AuthUnconfiguredError("No authenticated claims on this request")
    return claims


@auth_router.post(
    "/token",
    response_model=TokenPair,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Invalid credentials or auth not configured"},
        503: {"description": "Signing key not configured (fail-closed)"},
    },
)
async def token(
    request: Request,
    body: LoginRequest,
    user_service: UserService = get_user_service_dep,
    refresh_tokens: RefreshTokenService = get_refresh_token_service_dep,
) -> Response:
    """Classic login: resolve the user, verify bcrypt password, issue a token pair.

    On success sets the `__Host-refresh_token` httpOnly cookie and returns the
    short-lived access token in the body. Unknown user or wrong password both
    return the same generic 401 (flat timing via the store's dummy-compare), so
    neither the username's existence nor a wrong password can be probed.
    """
    user = await user_service.authenticate(body.username, body.password)
    if user is None:
        # Generic message; never reveal whether credentials or auth are valid.
        return JSONResponse({"detail": "Invalid credentials"}, status_code=401)

    access_token = sign_access_token(user.username, user.scopes, role=user.role)
    refresh_token = generate_refresh_token()
    refresh_hash = hash_refresh_token(refresh_token)
    await refresh_tokens.create_family(refresh_hash, user.username)

    response = JSONResponse(
        TokenPair(
            access_token=access_token,
            expires_in=settings.access_token_ttl_minutes * 60,
        ).model_dump()
    )
    _set_refresh_cookie(response, refresh_token)
    response.headers["Cache-Control"] = "no-store"
    return response


@auth_router.post(
    "/refresh",
    response_model=TokenPair,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Missing, revoked, or replayed refresh token"},
    },
)
async def refresh(
    request: Request,
    user_service: UserService = get_user_service_dep,
    refresh_tokens: RefreshTokenService = get_refresh_token_service_dep,
) -> Response:
    """Rotate the refresh token and issue a new access token.

    Reads the httpOnly cookie, rotates the family (replay detection revokes the
    whole family), and returns a fresh access token plus a rotated refresh
    cookie.
    """
    presented = _read_refresh_cookie(request)
    if not presented:
        return JSONResponse({"detail": "Missing refresh token"}, status_code=401)

    presented_hash = hash_refresh_token(presented)
    new_token = generate_refresh_token()
    new_hash = hash_refresh_token(new_token)

    subject = await refresh_tokens.rotate(presented_hash, new_hash)
    if subject is None:
        return JSONResponse(
            {"detail": "Refresh token invalid or replayed"},
            status_code=401,
        )

    user = await user_service.get_by_username(subject)
    if user is None or not user.is_active:
        # Family owner no longer exists/active; refuse to keep it alive.
        return JSONResponse(
            {"detail": "Refresh token invalid or replayed"},
            status_code=401,
        )

    access_token = sign_access_token(user.username, user.scopes, role=user.role)
    response = JSONResponse(
        TokenPair(
            access_token=access_token,
            expires_in=settings.access_token_ttl_minutes * 60,
        ).model_dump()
    )
    _set_refresh_cookie(response, new_token)
    response.headers["Cache-Control"] = "no-store"
    return response


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    refresh_tokens: RefreshTokenService = get_refresh_token_service_dep,
) -> Response:
    """Revoke the refresh-token family and clear the cookie."""
    presented = _read_refresh_cookie(request)
    if presented:
        await refresh_tokens.revoke_by_token(hash_refresh_token(presented))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    return response


@auth_router.get(
    "/me",
    response_model=MeResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"description": "Missing or invalid access token"}},
)
async def me(request: Request) -> MeResponse:
    """Return the operator identity, role, and scopes from the verified access token."""
    claims = _get_auth_claims(request)
    scopes = claims.get("scope", "").split()
    return MeResponse(
        subject=claims.get("sub", ""),
        role=claims.get("role", ROLE_USER),
        scopes=scopes,
    )
