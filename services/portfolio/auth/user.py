"""User domain layer (ADR-022, ADR-023) — no framework/DB imports.

`User` is the identity the rest of the system sees; `UserRow` (persistence)
maps onto it via `.to_domain()`. `PasswordHasher` is a port the application
layer (`UserService`) depends on, injectable for tests.
"""

from __future__ import annotations

import bcrypt
from pydantic import BaseModel, ConfigDict, EmailStr


ROLE_ADMIN = "admin"
ROLE_USER = "user"
SCOPE_READ = "cv:read"
SCOPE_MANAGE = "cv:manage"


class PasswordHasher:
    """Port for password hashing/verification (injectable for tests)."""

    def hash(self, password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def verify(self, password: str, hashed_password: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))


class User(BaseModel):
    """Domain entity — the identity the rest of the system sees.

    Exactly two roles (ADR-022): the privileged `admin` and the read-only
    `user`. The role is stamped on issued access tokens and gates the tailored
    surface (`/api/v1/cv/tailor` is admin-only).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    is_active: bool
    role: str = ROLE_USER

    @property
    def scopes(self) -> list[str]:
        """role → scopes. Admin gets manage on top of the base read scope."""
        base = [SCOPE_READ]
        if self.role == ROLE_ADMIN:
            base.append(SCOPE_MANAGE)
        return base
