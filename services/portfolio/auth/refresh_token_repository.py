"""Refresh-token repository — port (Protocol) + the one concrete adapter.

Mirrors `auth/user_repository.py`: the store depends on the Protocol, not on
`SqlAlchemyRefreshTokenRepository` directly.
"""

from __future__ import annotations

from typing import Protocol, cast

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.portfolio.auth.refresh_token_row import (
    RefreshTokenFamilyRow,
    RefreshTokenIndexRow,
)


class RefreshTokenRepository(Protocol):
    async def create_family(self, *, family_id: str, subject: str) -> None: ...
    async def get_family_by_token(
        self, token_hash: str
    ) -> RefreshTokenFamilyRow | None: ...
    async def get_family(self, family_id: str) -> RefreshTokenFamilyRow | None: ...
    async def rotate(
        self, *, family_id: str, presented_hash: str, new_hash: str
    ) -> bool: ...
    async def revoke(self, family_id: str) -> None: ...
    async def clear(self) -> None: ...


class SqlAlchemyRefreshTokenRepository:
    """Async SQLAlchemy refresh-token repository (Postgres, `asyncpg`).

    Takes the shared `async_sessionmaker` built once in `main.py`'s lifespan,
    same as `SqlAlchemyUserRepository`. Schema is Alembic-migrated.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_family(self, *, family_id: str, subject: str) -> None:
        """Insert a family and index its first token.

        The caller treats an IntegrityError (duplicate family_id) as the
        "already exists" case, matching the in-memory store's ValueError.
        """
        async with self._session_factory() as session:
            session.add(
                RefreshTokenFamilyRow(
                    family_id=family_id, subject=subject, current_hash=family_id
                )
            )
            session.add(RefreshTokenIndexRow(token_hash=family_id, family_id=family_id))
            await session.commit()

    async def get_family_by_token(
        self, token_hash: str
    ) -> RefreshTokenFamilyRow | None:
        """Resolve any issued token (current or rotated-away) to its family."""
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(RefreshTokenFamilyRow)
                    .join(
                        RefreshTokenIndexRow,
                        RefreshTokenIndexRow.family_id
                        == RefreshTokenFamilyRow.family_id,
                    )
                    .where(RefreshTokenIndexRow.token_hash == token_hash)
                )
            ).scalar_one_or_none()

    async def get_family(self, family_id: str) -> RefreshTokenFamilyRow | None:
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(RefreshTokenFamilyRow).where(
                        RefreshTokenFamilyRow.family_id == family_id
                    )
                )
            ).scalar_one_or_none()

    async def rotate(
        self, *, family_id: str, presented_hash: str, new_hash: str
    ) -> bool:
        """Advance the family's current token, atomically.

        The `current_hash == presented_hash AND NOT revoked` predicate lives in
        the UPDATE's WHERE clause rather than a preceding SELECT, so two
        concurrent refreshes presenting the same token cannot both win: exactly
        one UPDATE matches a row, the other sees rowcount 0. A SELECT-then-
        UPDATE pair would let both pass the check and defeat replay detection
        (the in-memory store used a threading.Lock for the same reason, which
        only ever covered a single process).

        Returns True if this call performed the rotation.
        """
        async with self._session_factory() as session:
            # cast: session.execute is typed Result[Any]; a DML statement
            # actually returns a CursorResult, which is what carries rowcount.
            result = cast(
                CursorResult,
                await session.execute(
                    update(RefreshTokenFamilyRow)
                    .where(
                        RefreshTokenFamilyRow.family_id == family_id,
                        RefreshTokenFamilyRow.current_hash == presented_hash,
                        RefreshTokenFamilyRow.revoked.is_(False),
                    )
                    .values(current_hash=new_hash)
                ),
            )
            if result.rowcount == 0:
                await session.rollback()
                return False
            session.add(RefreshTokenIndexRow(token_hash=new_hash, family_id=family_id))
            await session.commit()
            return True

    async def revoke(self, family_id: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(RefreshTokenFamilyRow)
                .where(RefreshTokenFamilyRow.family_id == family_id)
                .values(revoked=True)
            )
            await session.commit()

    async def clear(self) -> None:
        """Drop all families (test helper / lifecycle)."""
        async with self._session_factory() as session:
            await session.execute(delete(RefreshTokenIndexRow))
            await session.execute(delete(RefreshTokenFamilyRow))
            await session.commit()
