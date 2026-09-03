"""User repository — port (Protocol) + the one concrete adapter (ADR-023).

`UserService` depends on the `UserRepository` Protocol, not
`SqlAlchemyUserRepository` directly — the seam for swapping in a second
implementation later (a caching decorator, an in-memory fake) without
touching the service.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.portfolio.auth.user_row import UserRow


class UserRepository(Protocol):
    async def get_by_username(self, username: str) -> UserRow | None: ...
    async def create(self, *, user: UserRow) -> UserRow: ...


class SqlAlchemyUserRepository:
    """Async SQLAlchemy user repository (Postgres, `asyncpg`).

    Takes a shared `async_sessionmaker` (built once in `main.py`'s lifespan
    from one app-wide engine — see `services.portfolio.db`), not its own
    `db_url`/engine: engine lifecycle (open, dispose) is owned by whoever
    builds it, not by any one repository. Schema is Alembic-migrated, not
    derived from the model via `create_all`.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

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
