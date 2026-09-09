"""Document repository — port (Protocol) + the one concrete adapter.

The service depends on the Protocol, not the SQLAlchemy adapter.

Every method takes `tenant_id` and filters on it. That is not defensive
style: these rows are one tenant's CV and skill bank, and a query that
forgets the filter returns someone else's data as a plausible, complete
answer rather than failing. The parameter is keyword-only and required so
it cannot be dropped or transposed at a call site by accident.

Postgres row-level security backs that up: `_tenant_session` sets
`app.tenant_id` for the transaction, and the table's policy restricts every
statement to matching rows. A filter missed in Python then yields nothing
instead of another tenant's document. It only bites for a role without
BYPASSRLS, so the app must not connect as a superuser (or, on Cloud SQL, as
a member of cloudsqlsuperuser) — see the tenancy migration.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.portfolio.documents.document_row import DocumentRow


class DocumentRepository(Protocol):
    async def get(self, kind: str, *, tenant_id: int) -> DocumentRow | None: ...
    async def put(
        self, *, kind: str, payload: dict[str, Any], tenant_id: int
    ) -> DocumentRow: ...
    async def list_all(self, *, tenant_id: int) -> list[DocumentRow]: ...
    async def delete(self, kind: str, *, tenant_id: int) -> bool: ...


class SqlAlchemyDocumentRepository:
    """Async SQLAlchemy document repository (Postgres, `asyncpg`).

    Takes the shared `async_sessionmaker` built once in the app's lifespan,
    like every other repository here.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def _tenant_session(self, tenant_id: int) -> AsyncIterator[AsyncSession]:
        """A session whose transaction is pinned to one tenant for RLS.

        `SET LOCAL` is transaction-scoped, so the value cannot outlive the
        work and reach the next request that borrows this pooled connection
        — the leak a plain `SET` would introduce. Bound as a parameter, not
        interpolated: `set_config` takes a value, so a tenant id can never
        be read as SQL.
        """
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": str(tenant_id)},
                )
                yield session

    async def get(self, kind: str, *, tenant_id: int) -> DocumentRow | None:
        async with self._tenant_session(tenant_id) as session:
            return (
                await session.execute(
                    select(DocumentRow).where(
                        DocumentRow.tenant_id == tenant_id,
                        DocumentRow.kind == kind,
                    )
                )
            ).scalar_one_or_none()

    async def put(
        self, *, kind: str, payload: dict[str, Any], tenant_id: int
    ) -> DocumentRow:
        """Insert or replace one tenant's document, bumping its version.

        `version` increments server-side (`DocumentRow.version + 1`) so two
        concurrent writers cannot both read version 3 and both write 4. The
        conflict target is `(tenant_id, kind)`, so two tenants writing the
        same kind insert two rows instead of overwriting each other.
        """
        stmt = (
            insert(DocumentRow)
            .values(
                tenant_id=tenant_id,
                kind=kind,
                payload=payload,
                version=1,
                updated_at=datetime.now(UTC),
            )
            .on_conflict_do_update(
                index_elements=[DocumentRow.tenant_id, DocumentRow.kind],
                set_={
                    "payload": payload,
                    "version": DocumentRow.version + 1,
                    "updated_at": datetime.now(UTC),
                },
            )
            .returning(DocumentRow)
        )
        async with self._tenant_session(tenant_id) as session:
            return (await session.execute(stmt)).scalar_one()

    async def list_all(self, *, tenant_id: int) -> list[DocumentRow]:
        async with self._tenant_session(tenant_id) as session:
            result = await session.execute(
                select(DocumentRow)
                .where(DocumentRow.tenant_id == tenant_id)
                .order_by(DocumentRow.kind)
            )
            return list(result.scalars().all())

    async def delete(self, kind: str, *, tenant_id: int) -> bool:
        """Drop one tenant's document row. True when one was removed."""
        async with self._tenant_session(tenant_id) as session:
            result = await session.execute(
                sa_delete(DocumentRow)
                .where(
                    DocumentRow.tenant_id == tenant_id,
                    DocumentRow.kind == kind,
                )
                .returning(DocumentRow.id)
            )
            return result.scalars().first() is not None
