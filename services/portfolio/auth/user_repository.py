"""User repository — port (Protocol) + the one concrete adapter (ADR-023).

`UserService` depends on the `UserRepository` Protocol, not
`SqlAlchemyUserRepository` directly — the seam for swapping in a second
implementation later (a caching decorator, an in-memory fake) without
touching the service.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from services.portfolio.auth.user_row import UserRow


class UserRepository(Protocol):
    async def get_by_username(self, username: str) -> UserRow | None: ...
    async def create(self, *, user: UserRow) -> UserRow: ...


class SqlAlchemyUserRepository:
    """Async SQLAlchemy user repository (Postgres, `asyncpg`). Engine
    lifecycle (close) is managed by the app lifespan, not the repo; schema
    is Alembic-migrated, not derived from the model via `create_all`."""

    def __init__(self, db_url: str) -> None:
        self._engine = create_async_engine(db_url, future=True)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

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
