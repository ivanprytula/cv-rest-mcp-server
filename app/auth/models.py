"""Pydantic schemas for the auth endpoints."""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    """Classic login body: username + password.

    Interim slice (ADR-022): a single user (`operator`) is accepted; the
    username is validated against the same constant used as the token subject.
    Phase 2 replaces this with a user-lookup against the DB-backed user store.
    """

    username: str
    password: str


class TokenPair(BaseModel):
    """Access token response. The refresh token travels in a cookie, not here."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the access token expires


class MeResponse(BaseModel):
    """Identity returned by GET /api/v1/auth/me from the verified JWT claims."""

    subject: str
    role: str
    scopes: list[str]
