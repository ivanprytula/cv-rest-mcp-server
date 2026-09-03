"""Shared SQLAlchemy declarative base + engine/session factory (Phase 2, ADR-023).

One `Base.metadata` covers every ORM model app-wide — auth's `UserRow`,
`revisions/`'s `RevisionRow`, and whatever comes next — so Alembic
autogenerate sees the whole schema from one place. A feature module imports
`Base` from here rather than reaching into another feature module's
internals just to get the shared base class.

One `AsyncEngine` (and its `async_sessionmaker`) is built once in `main.py`'s
lifespan and shared by every repository's constructor — NOT one engine per
repository. Each engine opens its own connection pool (default
`pool_size=5 + max_overflow=10`); on a small Cloud SQL tier with a modest
`max_connections` ceiling, N repositories each opening their own engine
doesn't scale (N=50 models would be up to 750 possible connections). A
`Session` is cheap to open per call against one shared engine/pool.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def build_engine(db_url: str) -> AsyncEngine:
    return create_async_engine(db_url, future=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
