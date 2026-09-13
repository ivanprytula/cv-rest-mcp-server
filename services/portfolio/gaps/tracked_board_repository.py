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
        """Apply a partial update to one board, without losing a concurrent one.

        `SELECT ... FOR UPDATE` inside an explicit transaction, because this
        is a load-mutate-flush and the route builds `fields` from
        `model_dump(exclude_unset=True)` — partial updates are the norm. Two
        overlapping PATCHes would otherwise each load the row, each write back
        their own snapshot, and the later commit would silently clobber the
        fields the first one changed but the second never touched.

        The transaction is what makes the lock mean anything: without one
        spanning select through commit, the row lock would be released at the
        end of the SELECT's own implicit transaction and buy nothing.
        """
        async with self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        select(TrackedBoardRow)
                        .where(TrackedBoardRow.id == board_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if row is None:
                    return None
                for name, value in fields.items():
                    setattr(row, name, value)
                row.updated_at = datetime.now(UTC)
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
