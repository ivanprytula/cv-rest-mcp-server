"""User application service (ADR-022, ADR-023).

Construction happens once in `main.py`'s lifespan (`app.state.user_service`),
not as a module-level singleton — routes reach it via FastAPI's `Depends`
(`services.portfolio.dependencies.get_user_service`), matching the existing
`PdfService`/`get_pdf_service` pattern. Tests override the same dependency
via `app.dependency_overrides`, no `monkeypatch.setattr`-on-a-module needed.
"""

from __future__ import annotations

import uuid

import bcrypt

from services.portfolio.auth.user import ROLE_ADMIN, PasswordHasher, User
from services.portfolio.auth.user_repository import UserRepository
from services.portfolio.auth.user_row import UserRow
from services.portfolio.settings import settings


# Timing-attack hygiene (borrowed from the template's `authenticate`): an unknown
# username still bcrypt-verifies a dummy hash so login timing never reveals which
# of username/password failed. Generated at import -> guaranteed-valid hash.
_DUMMY_HASH: str = bcrypt.hashpw(b"timing-sentinel", bcrypt.gensalt()).decode("utf-8")


class UserService[R: UserRepository]:
    """Application service orchestrating repo + hasher.

    Generic over the repository implementation (`R`, bound to the
    `UserRepository` Protocol): a caller holding a `UserService[
    SqlAlchemyUserRepository]` gets `.repo` back as that concrete type with
    full static checking, while `UserService[UserRepository]` (or a bare
    `UserService`) stays correctly abstract wherever only the port matters —
    no behavior difference, purely a type-checking improvement.
    """

    def __init__(self, repo: R, hasher: PasswordHasher | None = None) -> None:
        self._repo = repo
        self._hasher = hasher or PasswordHasher()

    @property
    def repo(self) -> R:
        return self._repo

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
                id=str(uuid.uuid7()),
                username=username,
                email=email,
                hashed_password=self._hasher.hash(password),
                is_active=True,
                role=role,
            )
        )
        return created.to_domain()


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
