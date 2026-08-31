"""Async user store (ADR-022, Phase 2) — DDD-flavored + 12-factor config.

Boundaries (see docs/phase2-auth-pattern.md):
- **Domain**: `User` entity (identity + roles) and a `PasswordHasher` port.
- **Persistence**: `UserRepository` port with an async SQLAlchemy implementation
  on `aiosqlite` for the interim. The repo exposes raw load/save of a `UserRow`
  (which carries `hashed_password`); business rules (auth, seeding) live in the
  application service, so swapping the DB replaces only the repo impl — domain
  and service stay put.
- **Application service**: `authenticate()` / `seed_first_admin()` orchestrate
  repo + hasher (the template's `crud.authenticate`, async-native).

Async-native (borrowed from the 45k-star full-stack template, adapted):
`create_async_engine` + async sessions. Because the repo talks to the engine,
Phase-2 Postgres is a one-line driver change (`asyncpg`) with identical async
session code — no rewrite, easy to scale across services.

12-factor: all config via env (`settings`). The store is bound to
`settings.user_db_path` at construction; a plain file path is the production form.

Model split mirrors the template: the ORM `UserRow` carries `hashed_password`
(never serialized); the domain `User` schema is what auth/API code sees.

Refresh-token families stay in-memory (`token_store.RefreshTokenStore`) — the DB
stores users, not sessions.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path

import bcrypt
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.settings import settings


ROLE_ADMIN = "admin"
ROLE_USER = "user"
SCOPE_READ = "cv:read"
SCOPE_MANAGE = "cv:manage"


def sqlite_url_for(path: Path | str) -> str:
    """Build an aiosqlite URL for a filesystem path (or `:memory:`)."""
    if str(path) == ":memory:":
        return "sqlite+aiosqlite://"
    return f"sqlite+aiosqlite:///{path}"


# ---------------------------------------------------------------------------
# Domain
# ---------------------------------------------------------------------------


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
    surface (`/cv/tailor` is admin-only).
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
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


# ---------------------------------------------------------------------------
# Persistence port + SQLAlchemy implementation
# ---------------------------------------------------------------------------


class UserRepository(ABC):
    """Port: raw load/save of users. Phase-2 Postgres adds another impl."""

    @abstractmethod
    async def get_by_username(self, username: str) -> UserRow | None: ...

    @abstractmethod
    async def create(self, *, user: UserRow) -> UserRow: ...


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    """ORM row. `hashed_password` is internal; expose via `.to_domain()`."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    role: Mapped[str] = mapped_column(String(16), default=ROLE_USER)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    def to_domain(self) -> User:
        return User(
            id=self.id,
            username=self.username,
            email=self.email,
            is_active=self.is_active,
            role=self.role,
        )


class SqlAlchemyUserRepository(UserRepository):
    """Async SQLAlchemy implementation of the user repository (`aiosqlite`)."""

    def __init__(self, db_url: str) -> None:
        self._engine = create_async_engine(db_url, future=True)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )

    async def init_schema(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()

    async def get_by_username(self, username: str) -> UserRow | None:
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(UserRow).where(UserRow.username == username)
                )
            ).scalar_one_or_none()

    async def create(self, *, user: UserRow) -> UserRow:
        async with self._session_factory() as session:
            session.add(user)
            await session.commit()
        return user


# ---------------------------------------------------------------------------
# Application service
# ---------------------------------------------------------------------------


# Timing-attack hygiene (borrowed from the template's `authenticate`): an unknown
# username still bcrypt-verifies a dummy hash so login timing never reveals which
# of username/password failed. Generated at import -> guaranteed-valid hash.
_DUMMY_HASH: str = bcrypt.hashpw(b"timing-sentinel", bcrypt.gensalt()).decode("utf-8")


class UserService:
    """Application service orchestrating repo + hasher (the seam swapped at
    Phase 2 Postgres is only the repo constructor)."""

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
                id=str(uuid.uuid4()),
                username=username,
                email=email,
                hashed_password=self._hasher.hash(password),
                is_active=True,
                role=role,
            )
        )
        return created.to_domain()

    async def init_schema(self) -> None:
        if isinstance(self._repo, SqlAlchemyUserRepository):
            await self._repo.init_schema()

    async def close(self) -> None:
        if isinstance(self._repo, SqlAlchemyUserRepository):
            await self._repo.close()


# Module singleton used by the auth routes. Bound at import from settings (the
# engine is lazy — no disk touch until a login/seed actually runs). Tests
# replace this with a per-test repo/service via the fixture (like token_store).
user_service = UserService(
    SqlAlchemyUserRepository(sqlite_url_for(settings.user_db_path))
)


async def seed_first_admin_from_settings(
    service: UserService | None = None,
) -> None:
    """12-factor startup seed: read FIRST_ADMIN_* settings and create the first
    admin if missing. Idempotent; skips when no password is configured (fail-open
    on seeding — login still fail-closes). Called from the app lifespan."""
    svc = service or user_service
    password = settings.first_admin_password
    if settings.first_admin_password_file is not None:
        password = settings.first_admin_password_file.read_text(
            encoding="utf-8"
        ).strip()
    if not password:
        return
    await svc.seed_first_admin(
        username=settings.first_admin_username,
        email=settings.first_admin_email,
        password=password,
        role=ROLE_ADMIN,
    )
