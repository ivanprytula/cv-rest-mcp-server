"""Auth module for the private SPA console (Phase 1c, ADR-022).

api-core is the HS256 JWT issuer (single shared secret, easy to replicate
across stateless services; see ADR-022). The operator logs in with a
bcrypt-hashed password (fail-closed when unconfigured, like TailorAuth); on
success they get a short-lived access token (memory-only in the SPA, sent as
`Authorization: Bearer`) plus a long-lived refresh token delivered as a
`__Host-` httpOnly, Secure, SameSite=None cookie consumed only by
`POST /api/v1/auth/refresh`. The refresh token rotates on every use with family
reuse-detection in an in-memory store (Postgres in Phase 2).
"""

from app.auth.middleware import CredentialedCORSMiddleware, JWTAuthMiddleware
from app.auth.routes import auth_router


__all__ = [
    "CredentialedCORSMiddleware",
    "JWTAuthMiddleware",
    "auth_router",
]
