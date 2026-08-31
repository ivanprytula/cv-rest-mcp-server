"""Cryptographic primitives for the auth module.

HS256 (symmetric) signing: api-core holds a single shared secret
(`jwt_signing_key`) and is the issuer AND the only verifier today, so it signs
and validates with the same value. HS256 (rather than asymmetric ES256) is a
deliberate choice for easy horizontally-scaling stateless services: every
replica shares one inline `.env` secret, and any microservice that needs to
validate a token is given the same shared secret — no PEM key management. The
cost (any validator could also forge) is acceptable because the fleet is
operator-owned and trusted. Refresh tokens are random opaque strings hashed at
rest (SHA-256 + pepper); login password verification lives in
`app/auth/user_store.py` (bcrypt, constant-time per compare).

Everything here is fail-closed: an empty signing secret raises rather than
silently weakening auth.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

import jwt

from app.settings import settings


# Claims present on every access token. `aud` may be a string or a list.
_REQUIRED_SCHEME = "HS256"


class AuthUnconfiguredError(RuntimeError):
    """Raised when an auth operation needs a secret that is not configured.

    Mirrors TailorAuth's fail-closed posture: no silent downgrade. Routes map
    this to 503.
    """


def _jwt_secret() -> str:
    key = settings.jwt_signing_key.strip()
    if not key:
        raise AuthUnconfiguredError(
            "JWT_SIGNING_KEY not configured; auth endpoints are disabled (fail-closed)"
        )
    return key


def sign_access_token(subject: str, scopes: list[str], *, role: str) -> str:
    """Issue a short-lived HS256 access token for *subject* with *scopes* + *role*."""
    import time

    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + settings.access_token_ttl_minutes * 60,
        "scope": " ".join(scopes),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=_REQUIRED_SCHEME)


def verify_access_token(token: str) -> dict[str, Any]:
    """Decode and verify an access token, returning its claims.

    api-core signs and validates with the same shared HS256 secret, and any
    microservice that needs to validate is handed the same secret.

    Raises `jwt.InvalidTokenError` (and subclasses) on any failure: bad
    signature, expired, wrong issuer, wrong audience.
    """
    return jwt.decode(
        token,
        _jwt_secret(),
        algorithms=[_REQUIRED_SCHEME],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )


def hash_refresh_token(token: str) -> str:
    """Hash an opaque refresh token with the pepper (salted at rest).

    `hmac.compare_digest`-comparable; the pepper is a static env secret, so the
    stored hash is not directly reversible without it.
    """
    pepper = settings.refresh_token_pepper.encode("utf-8")
    return hmac.new(pepper, token.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_refresh_token() -> str:
    """Return a fresh cryptographically-random opaque refresh token."""
    return secrets.token_urlsafe(64)
