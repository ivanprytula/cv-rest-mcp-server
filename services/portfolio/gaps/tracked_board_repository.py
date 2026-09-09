"""Tracked-board repository — port (Protocol) + the one concrete adapter.

`TrackedBoardService` depends on the `TrackedBoardRepository` Protocol, not
the SQLAlchemy adapter, mirroring `GapRepository`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.portfolio.gaps.tracked_board_row import TrackedBoardRow


class TrackedBoardRepository(Protocol):
    async def create(
        self,
        *,
        kind: str,
        company_name: str,
        company_slug: str | None,
        url: str | None,
        notes: str | None,
        group: str | None,
    ) -> TrackedBoardRow: ...
    async def list_all(
        self, *, active_only: bool, group: str | None = None
    ) -> list[TrackedBoardRow]: ...
    async def get(self, board_id: int) -> TrackedBoardRow | None: ...
    async def update(
        self, board_id: int, fields: dict[str, Any]
    ) -> TrackedBoardRow | None: ...
    async def delete(self, board_id: int) -> bool: ...


class SqlAlchemyTrackedBoardRepository:
    """Async SQLAlchemy tracked-board repository (Postgres, `asyncpg`).

    Takes the shared `async_sessionmaker` built once in the app's lifespan,
    not its own engine — same rationale as `SqlAlchemyGapRepository`.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        *,
        kind: str,
        company_name: str,
        company_slug: str | None,
        url: str | None,
        notes: str | None,
        group: str | None,
    ) -> TrackedBoardRow:
        row = TrackedBoardRow(
            kind=kind,
            company_name=company_name,
            company_slug=company_slug,
            url=url,
            notes=notes,
            group=group,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def list_all(
        self, *, active_only: bool, group: str | None = None
    ) -> list[TrackedBoardRow]:
        stmt = select(TrackedBoardRow).order_by(TrackedBoardRow.id)
        if active_only:
            stmt = stmt.where(TrackedBoardRow.active.is_(True))
        if group is not None:
            stmt = stmt.where(TrackedBoardRow.group == group)
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get(self, board_id: int) -> TrackedBoardRow | None:
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(TrackedBoardRow).where(TrackedBoardRow.id == board_id)
                )
            ).scalar_one_or_none()

    async def update(
        self, board_id: int, fields: dict[str, Any]
    ) -> TrackedBoardRow | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(TrackedBoardRow).where(TrackedBoardRow.id == board_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            for name, value in fields.items():
                setattr(row, name, value)
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return row

    async def delete(self, board_id: int) -> bool:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(TrackedBoardRow).where(TrackedBoardRow.id == board_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True
