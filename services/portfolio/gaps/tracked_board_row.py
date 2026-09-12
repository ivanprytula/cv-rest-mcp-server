"""Tracked-board ORM row — persistence layer, Alembic-migrated schema.

Registry of what to poll, distinct from `AtsBoardRow` (the fetch-cache table
keyed by (source, company_slug), written only after a successful fetch).
This table exists independent of fetch state: a board is tracked the moment
an operator creates it, whether or not it has ever been fetched.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from services.portfolio.db import Base
from services.portfolio.gaps.tracked_board import TrackedBoard


KIND_GREENHOUSE = "greenhouse"
KIND_LEVER = "lever"
KIND_ASHBY = "ashby"
KIND_URL_ONLY = "url_only"

# Must match services.portfolio.gaps.ats._FETCHERS's keys.
API_BACKED_KINDS = (KIND_GREENHOUSE, KIND_LEVER, KIND_ASHBY)
ALL_KINDS = (*API_BACKED_KINDS, KIND_URL_ONLY)


class TrackedBoardRow(Base):
    """One tracked company: an API-backed ATS board, or a career-page URL.

    ``company_slug`` is required for API-backed kinds (identifies the board
    on its portal) and absent for ``url_only``; ``url`` is the reverse. The
    unique constraint is only meaningful for API-backed kinds — Postgres
    treats NULLs as distinct, so multiple `url_only` rows (both NULL
    `company_slug`) never collide on it.
    """

    __tablename__ = "tracked_boards"
    __table_args__ = (
        UniqueConstraint("kind", "company_slug", name="uq_tracked_boards_kind_slug"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32))
    company_name: Mapped[str] = mapped_column(String(255))
    company_slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Free-text operator notes (e.g. "redirects to Greenhouse via agency X"),
    # for observations made before any fetcher exists to act on them —
    # nothing here is read by sync_board; it's purely for the operator.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional named list (e.g. "priority", "fintech") for organization and
    # for scoping which boards a given Cloud Scheduler job's /trigger?group=
    # run polls. Independent of `kind` — a board's group has no bearing on
    # whether it's API-backed or url_only.
    group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # No tenant_id: board polling stays admin-only/shared (Phase 3e decision),
    # not per-tenant. A tracked board is "what we poll," not "who owns it" —
    # unlike JobPostingRow.tenant_id. Adding it later would be additive.
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    def to_domain(self) -> TrackedBoard:
        return TrackedBoard.model_validate(self)
