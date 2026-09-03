"""Shared SQLAlchemy declarative base (Phase 2, ADR-023).

One `Base.metadata` covers every ORM model app-wide — auth's `UserRow`
today, future `RevisionRow`/`RefreshTokenRow` next — so Alembic autogenerate
sees the whole schema from one place. A feature module (e.g. a future
`revisions/` package) imports `Base` from here rather than reaching into
another feature module's internals just to get the shared base class.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
