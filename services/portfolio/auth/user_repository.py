"""User repository — port (Protocol) + the one concrete adapter (ADR-023).

`UserService` depends on the `UserRepository` Protocol, not
`SqlAlchemyUserRepository` directly — the seam for swapping in a second
implementation later (a caching decorator, an in-memory fake) without
touching the service.
"""

from __future__ import annotations

from typing import Protocol, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.portfolio.auth.user_row import UserRow


class UserRepository(Protocol):
    async def get_by_username(self, username: str) -> UserRow | None: ...
    async def create(self, *, user: UserRow) -> UserRow: ...
    async def set_active(self, *, username: str, is_active: bool) -> bool: ...
    async def set_role(self, *, username: str, role: str) -> bool: ...
    async def list_all(self) -> list[UserRow]: ...


class SqlAlchemyUserRepository:
    """Async SQLAlchemy user repository (Postgres, `asyncpg`).

    Takes a shared `async_sessionmaker` (built once in the app's lifespan
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

    async def set_active(self, *, username: str, is_active: bool) -> bool:
        """Flip a user's active flag. Returns False if no such user exists."""
        async with self._session_factory() as session:
            # cast: session.execute is typed Result[Any]; a DML statement
            # actually returns a CursorResult, which is what carries rowcount.
            result = cast(
                CursorResult,
                await session.execute(
                    update(UserRow)
                    .where(UserRow.username == username)
                    .values(is_active=is_active)
                ),
            )
            await session.commit()
            return result.rowcount > 0

    async def set_role(self, *, username: str, role: str) -> bool:
        """Change a user's role. Returns False if no such user exists."""
        async with self._session_factory() as session:
            result = cast(
                CursorResult,
                await session.execute(
                    update(UserRow)
                    .where(UserRow.username == username)
                    .values(role=role)
                ),
            )
            await session.commit()
            return result.rowcount > 0

    async def list_all(self) -> list[UserRow]:
        async with self._session_factory() as session:
            result = await session.execute(select(UserRow).order_by(UserRow.username))
            return list(result.scalars().all())
