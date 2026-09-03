"""Refresh-token ORM rows (ADR-022/023) — persistence layer, Alembic-migrated.

Two tables mirror the two structures the in-memory store kept: a family's
state, and an index of every hash ever issued to that family. The index is
what makes replay detection work — a rotated-away token is still recognised
as belonging to its family, so presenting it can revoke the whole lineage.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from services.portfolio.db import Base


class RefreshTokenFamilyRow(Base):
    """One refresh-token lineage. `family_id` is the first token's hash."""

    __tablename__ = "refresh_token_families"

    # HMAC-SHA256 hex digest (64 chars) of the first token in the lineage.
    family_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), index=True)
    current_hash: Mapped[str] = mapped_column(String(64))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class RefreshTokenIndexRow(Base):
    """Every hash ever issued -> its family, so replays resolve after rotation.

    `ondelete="CASCADE"` keeps the index from outliving its family when a
    future cleanup job prunes expired lineages.
    """

    __tablename__ = "refresh_token_index"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    family_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("refresh_token_families.family_id", ondelete="CASCADE"),
        index=True,
    )
