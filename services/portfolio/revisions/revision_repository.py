"""Revision repository — port (Protocol) + the one concrete adapter (ADR-023).

`RevisionService` depends on the `RevisionRepository` Protocol, not
`SqlAlchemyRevisionRepository` directly, mirroring `auth/user_repository.py`.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.portfolio.revisions.revision_row import RevisionRow


class RevisionRepository(Protocol):
    async def create(self, *, revision: RevisionRow) -> RevisionRow: ...
    async def get_by_id(self, revision_id: int) -> RevisionRow | None: ...
    async def list_all(self) -> list[RevisionRow]: ...


class SqlAlchemyRevisionRepository:
    """Async SQLAlchemy revision repository (Postgres, `asyncpg`).

    Takes a shared `async_sessionmaker` (built once in `main.py`'s lifespan
    from one app-wide engine — see `services.portfolio.db`), not its own
    `db_url`/engine — same rationale as `SqlAlchemyUserRepository`. Schema
    is Alembic-migrated, not derived from the model via `create_all`.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, *, revision: RevisionRow) -> RevisionRow:
        async with self._session_factory() as session:
            session.add(revision)
            await session.commit()
        return revision

    async def get_by_id(self, revision_id: int) -> RevisionRow | None:
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(RevisionRow).where(RevisionRow.id == revision_id)
                )
            ).scalar_one_or_none()

    async def list_all(self) -> list[RevisionRow]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(RevisionRow).order_by(RevisionRow.created_at.desc())
            )
            return list(result.scalars().all())
