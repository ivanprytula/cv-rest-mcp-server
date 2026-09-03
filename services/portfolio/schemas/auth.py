"""Pydantic schemas for the auth endpoints."""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    """Classic login body: username + password (ADR-022, ADR-023).

    Looked up against the Postgres-backed user store
    (`services.portfolio.auth.user_service.UserService`).
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
