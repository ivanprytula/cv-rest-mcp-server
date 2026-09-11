"""User application service (ADR-022, ADR-023).

Construction happens once in the app's lifespan (`app.state.user_service`),
not as a module-level singleton — routes reach it via FastAPI's `Depends`
(`services.portfolio.dependencies.get_user_service`), matching the existing
`PdfService`/`get_pdf_service` pattern. Tests override the same dependency
via `app.dependency_overrides`, no `monkeypatch.setattr`-on-a-module needed.
"""

from __future__ import annotations

import bcrypt

from services.portfolio.auth.user import (
    ROLE_ADMIN,
    ROLE_USER,
    PasswordHasher,
    User,
)
from services.portfolio.auth.user_repository import UserRepository
from services.portfolio.auth.user_row import UserRow
from services.portfolio.settings import settings
from services.portfolio.tenancy import TenantId


# Timing-attack hygiene (borrowed from the template's `authenticate`): an unknown
# username still bcrypt-verifies a dummy hash so login timing never reveals which
# of username/password failed. Generated at import -> guaranteed-valid hash.
_DUMMY_HASH: str = bcrypt.hashpw(b"timing-sentinel", bcrypt.gensalt()).decode("utf-8")


class UserService:
    """Application service orchestrating repo + hasher.

    Depends on the `UserRepository` Protocol, not a concrete implementation
    — the seam for swapping in a different repo without touching callers.
    """

    def __init__(
        self, repo: UserRepository, hasher: PasswordHasher | None = None
    ) -> None:
        self._repo = repo
        self._hasher = hasher or PasswordHasher()

    async def get_by_username(self, username: str) -> User | None:
        row = await self._repo.get_by_username(username)
        return row.to_domain() if row else None

    async def authenticate(self, username: str, password: str) -> User | None:
        """Resolve (username, password) → User, or None with flat timing.

        An unknown username still runs a dummy bcrypt compare so a wrong username
        and a wrong password take ~the same time. Returns None for missing /
        inactive / mismatched credentials, and when the store is unconfigured.
        """
        row = await self._repo.get_by_username(username)
        if row is None:
            bcrypt.checkpw(password.encode("utf-8"), _DUMMY_HASH.encode("utf-8"))
            return None
        if not row.is_active:
            return None
        if not self._hasher.verify(password, row.hashed_password):
            return None
        return row.to_domain()

    async def register(
        self, *, username: str, email: str, password: str
    ) -> User | None:
        """Create a self-service account, or None if the username is taken.

        Always `ROLE_USER`: registering can never mint an admin. The new
        user owns their own tenant — their id — and `cv:manage` lets them
        edit only their own documents.

        None means "username taken", the one failure a caller must render
        differently; a repository error still raises, since a failed write
        that reports success would leave the user unable to log in.
        """
        if not password:
            return None
        if await self._repo.get_by_username(username) is not None:
            return None
        created = await self._repo.create(
            user=UserRow(
                username=username,
                email=email,
                hashed_password=self._hasher.hash(password),
                is_active=True,
                role=ROLE_USER,
            )
        )
        return created.to_domain()

    async def set_active(self, *, username: str, is_active: bool) -> bool:
        """Enable or disable a user's account. Returns False if unknown.

        Disabling does not touch already-issued access tokens (stateless,
        ≤`access_token_ttl_minutes` old) — `authenticate()` already refuses
        an inactive user, so this alone blocks new logins. Callers that also
        want existing sessions cut immediately should revoke the user's
        refresh-token families too (see `auth/routes.py`'s admin route).
        """
        return await self._repo.set_active(username=username, is_active=is_active)

    async def set_role(self, *, username: str, role: str) -> bool:
        """Change a user's role (`admin`/`user`). Returns False if unknown.

        Takes effect on the user's next login/refresh — the role already on
        an issued access token is stale until it expires or is refreshed,
        same statelessness caveat as `set_active`.
        """
        return await self._repo.set_role(username=username, role=role)

    async def list_all(self) -> list[User]:
        rows = await self._repo.list_all()
        return [row.to_domain() for row in rows]

    async def seed_first_admin(
        self, *, username: str, email: str, password: str, role: str = ROLE_ADMIN
    ) -> User | None:
        """Idempotently create the first admin (or caller-supplied role) user.

        Returns the created (or existing) user; None if *password* is empty
        (nothing configured — fail-open on seeding, fail-closed on login).
        """
        if not password:
            return None
        existing = await self._repo.get_by_username(username)
        if existing is not None:
            return existing.to_domain()
        created = await self._repo.create(
            user=UserRow(
                username=username,
                email=email,
                hashed_password=self._hasher.hash(password),
                is_active=True,
                role=role,
            )
        )
        return created.to_domain()


async def resolve_operator_tenant_id(service: UserService) -> TenantId | None:
    """The tenant that owns install-wide work: the configured first admin.

    Gap analysis and the ATS refresh run for the installation, not for a
    caller — the scheduler has no request and no token — so they need a
    tenant chosen by configuration rather than by a JWT. Until gap rows are
    themselves tenant-scoped (a later phase), that is the operator's.
    """
    user = await service.get_by_username(settings.first_admin_username)
    return TenantId(user.id) if user else None


async def seed_first_admin_from_settings(service: UserService) -> None:
    """12-factor startup seed: read FIRST_ADMIN_* settings and create the first
    admin if missing. Idempotent; skips when no password is configured (fail-open
    on seeding — login still fail-closes). Called from the app lifespan."""
    password = settings.first_admin_password
    if settings.first_admin_password_file is not None:
        password = settings.first_admin_password_file.read_text(
            encoding="utf-8"
        ).strip()
    if not password:
        return
    await service.seed_first_admin(
        username=settings.first_admin_username,
        email=settings.first_admin_email,
        password=password,
        role=ROLE_ADMIN,
    )
