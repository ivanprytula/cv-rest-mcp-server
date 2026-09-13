"""Transactional-outbox and idempotency-key ORM rows — Alembic-migrated schema.

Both tables exist to make a write and its side effect agree. `EventOutboxRow`
pairs a domain event with the transaction that caused it, so a commit-then-
failed-publish cannot lose the event. `IdempotencyKeyRow` pairs a client's
retry token with the response it already produced, so a retried POST replays
instead of duplicating.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from services.portfolio.db import Base


class EventOutboxRow(Base):
    """One domain event, written in the same transaction as the state change.

    `published_at IS NULL` means pending; the relay
    (`refresh_trigger.dispatch_outbox`) drains those in `id` order and stamps
    them once Pub/Sub has accepted them. Rows are kept after publishing so the
    table doubles as an audit trail, and pruned on a 7-day window by the relay
    itself rather than a separate cleanup job.

    Unlike every other tenant-scoped table here, this one carries no
    row-level-security policy — see the migration's comment and ADR. The relay
    drains all tenants in one pass as a trusted internal process with no
    request tenant to scope to, so `tenant_id` is data (it goes into the event
    payload), not an isolation boundary.
    """

    __tablename__ = "event_outbox"
    __table_args__ = (
        # The relay only ever scans pending rows, so the index it uses stays
        # small even as the published backlog grows.
        Index(
            "ix_event_outbox_pending",
            "id",
            postgresql_where="published_at IS NULL",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class IdempotencyKeyRow(Base):
    """A client-supplied retry token and the response it already produced.

    The composite primary key `(tenant_id, key)` is the lock: inserting the
    reservation row IS the claim, so two concurrent retries of the same
    request cannot both proceed past it. Keys are per-tenant — one tenant's
    token must never replay another's response body.
    """

    __tablename__ = "idempotency_keys"

    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
