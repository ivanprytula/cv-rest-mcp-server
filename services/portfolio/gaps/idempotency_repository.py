"""Idempotency-key store — port (Protocol) + the one concrete adapter.

Small and deliberately unshared: one route needs this today
(`POST /api/v1/postings`). The other POST routes are admin-only or already
upsert-idempotent, so a dependency spanning all of them would be scaffolding
for a problem they do not have.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.portfolio.events.outbox_row import IdempotencyKeyRow
from services.portfolio.tenancy import TenantId


class IdempotencyRepository(Protocol):
    async def reserve(self, key: str, *, tenant_id: TenantId) -> bool: ...
    async def get_response(
        self, key: str, *, tenant_id: TenantId
    ) -> dict[str, Any] | None: ...
    async def store_response(
        self, key: str, response_body: dict[str, Any], *, tenant_id: TenantId
    ) -> None: ...


class SqlAlchemyIdempotencyRepository:
    """Async SQLAlchemy idempotency-key store (Postgres, `asyncpg`).

    Takes the shared `async_sessionmaker` built once in the app's lifespan,
    same rationale as `SqlAlchemyGapRepository`.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def _tenant_session(self, session: AsyncSession, tenant_id: TenantId) -> None:
        """Pin this transaction to one tenant, for the table's RLS policy.

        `SET LOCAL`, so the pinned tenant cannot leak to the next request that
        borrows this pooled connection — same mechanism as
        `SqlAlchemyGapRepository._tenant_session`.
        """
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

    async def reserve(self, key: str, *, tenant_id: TenantId) -> bool:
        """Claim a key, returning True if this caller now owns it.

        The INSERT *is* the lock: `ON CONFLICT DO NOTHING` on the composite
        primary key means two concurrent retries of the same request cannot
        both be told they own it, with no check-then-act window between. A
        False return means a previous request got there first and its response
        should be replayed.

        The reserved row carries an empty `response_body` until the real work
        finishes — `store_response` fills it in.
        """
        async with self._session_factory() as session:
            async with session.begin():
                await self._tenant_session(session, tenant_id)
                result = await session.execute(
                    insert(IdempotencyKeyRow)
                    .values(
                        tenant_id=tenant_id,
                        key=key,
                        response_body={},
                        created_at=datetime.now(UTC),
                    )
                    .on_conflict_do_nothing(constraint="pk_idempotency_keys")
                    .returning(IdempotencyKeyRow.key)
                )
                return result.scalar_one_or_none() is not None

    async def get_response(
        self, key: str, *, tenant_id: TenantId
    ) -> dict[str, Any] | None:
        """The stored response for a key, or None if it has none yet.

        None covers both "no such key" and "reserved but still in flight" —
        the caller cannot replay either, and telling them apart would only
        matter to a retry policy this route does not have.
        """
        async with self._session_factory() as session:
            async with session.begin():
                await self._tenant_session(session, tenant_id)
                row = (
                    await session.execute(
                        select(IdempotencyKeyRow).where(
                            IdempotencyKeyRow.tenant_id == tenant_id,
                            IdempotencyKeyRow.key == key,
                        )
                    )
                ).scalar_one_or_none()
                if row is None or not row.response_body:
                    return None
                return row.response_body

    async def store_response(
        self, key: str, response_body: dict[str, Any], *, tenant_id: TenantId
    ) -> None:
        """Record what this key's request returned, for a later retry to replay."""
        async with self._session_factory() as session:
            async with session.begin():
                await self._tenant_session(session, tenant_id)
                await session.execute(
                    insert(IdempotencyKeyRow)
                    .values(
                        tenant_id=tenant_id,
                        key=key,
                        response_body=response_body,
                        created_at=datetime.now(UTC),
                    )
                    .on_conflict_do_update(
                        constraint="pk_idempotency_keys",
                        set_={"response_body": response_body},
                    )
                )
