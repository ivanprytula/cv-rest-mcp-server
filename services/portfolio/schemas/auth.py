"""Pydantic schemas for the auth endpoints."""

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Classic login body: username + password (ADR-022, ADR-023).

    Looked up against the Postgres-backed user store
    (`services.portfolio.auth.user_service.UserService`).
    """

    username: str
    password: str


class RegisterRequest(BaseModel):
    """Self-service signup body.

    Bounds are validation, not policy: an unbounded username or password is
    a free write-amplification and bcrypt-CPU lever for an unauthenticated
    caller. bcrypt itself truncates beyond 72 bytes.

    Email is not collected at signup (the site is pre-launch and this
    sidesteps PII/GDPR handling until it's actually needed) — a user can
    set one later from their profile. See `ProfileResponse`.
    """

    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=12, max_length=128)


class RegisteredUser(BaseModel):
    """What signup returns: identity only, never a token.

    Registering does not sign you in — the client posts to /auth/token
    afterwards, so there is exactly one path that mints credentials. `email`
    is a server-generated placeholder at this point — see
    `UserService.register` — not one the caller supplied.
    """

    id: int
    username: str
    email: EmailStr


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


class UserActiveStatus(BaseModel):
    """What the admin disable/enable-user endpoints return."""

    username: str
    is_active: bool


class SetUserRoleRequest(BaseModel):
    """Body for the admin set-role endpoint."""

    role: str = Field(pattern=r"^(admin|user)$")


class UserRoleStatus(BaseModel):
    """What the admin set-role endpoint returns."""

    username: str
    role: str


class ProfileResponse(BaseModel):
    """Identity returned by GET /api/v1/auth/profile — DB-backed, unlike
    /api/v1/auth/me (claims-only), so it can carry `email`. `email` is
    always present, but `email_is_placeholder` tells the caller whether
    it's the server-generated one from registration (see
    `UserService.register`) rather than one the user actually set — the
    profile page uses this to nudge the user to add a real one.
    """

    username: str
    email: EmailStr
    email_is_placeholder: bool
    role: str


class SetEmailRequest(BaseModel):
    """Body for the self-service set-email endpoint — replaces the caller's
    (possibly placeholder) email with a real one. Not nullable: every
    account always has an email, so there's no "clear it" case.
    """

    email: EmailStr
