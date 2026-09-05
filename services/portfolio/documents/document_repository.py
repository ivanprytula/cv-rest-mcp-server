"""Document repository — port (Protocol) + the one concrete adapter.

Mirrors `revisions/revision_repository.py`: the service depends on the
Protocol, not the SQLAlchemy adapter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.portfolio.documents.document_row import DocumentRow


class DocumentRepository(Protocol):
    async def get(self, kind: str) -> DocumentRow | None: ...
    async def put(self, *, kind: str, payload: dict[str, Any]) -> DocumentRow: ...
    async def list_all(self) -> list[DocumentRow]: ...


class SqlAlchemyDocumentRepository:
    """Async SQLAlchemy document repository (Postgres, `asyncpg`).

    Takes the shared `async_sessionmaker` built once in `main.py`'s lifespan,
    like every other repository here.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, kind: str) -> DocumentRow | None:
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(DocumentRow).where(DocumentRow.kind == kind)
                )
            ).scalar_one_or_none()

    async def put(self, *, kind: str, payload: dict[str, Any]) -> DocumentRow:
        """Insert or replace a document, bumping its version.

        `version` increments server-side (`DocumentRow.version + 1`) so two
        concurrent writers cannot both read version 3 and both write 4.
        """
        stmt = (
            insert(DocumentRow)
            .values(kind=kind, payload=payload, version=1, updated_at=datetime.now(UTC))
            .on_conflict_do_update(
                index_elements=[DocumentRow.kind],
                set_={
                    "payload": payload,
                    "version": DocumentRow.version + 1,
                    "updated_at": datetime.now(UTC),
                },
            )
            .returning(DocumentRow)
        )
        async with self._session_factory() as session:
            row = (await session.execute(stmt)).scalar_one()
            await session.commit()
            return row

    async def list_all(self) -> list[DocumentRow]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(DocumentRow).order_by(DocumentRow.kind)
            )
            return list(result.scalars().all())
