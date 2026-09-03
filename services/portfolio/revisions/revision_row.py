"""Revision ORM row (ADR-023) — persistence layer, Alembic-migrated schema."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from services.portfolio.db import Base
from services.portfolio.revisions.revision import Revision


class RevisionRow(Base):
    """ORM row. Postgres-only (`JSONB`) — no SQLite-compat constraint to
    design around now that both tests and prod run real Postgres."""

    __tablename__ = "revisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    jd_hash: Mapped[str] = mapped_column(String(64))
    tailored_cv: Mapped[dict] = mapped_column(JSONB)
    promoted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    def to_domain(self) -> Revision:
        return Revision(
            id=self.id,
            name=self.name,
            created_at=self.created_at,
            jd_hash=self.jd_hash,
            tailored_cv=self.tailored_cv,
            promoted=self.promoted,
        )
