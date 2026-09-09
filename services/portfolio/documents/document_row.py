"""Operator document ORM row — persistence layer, Alembic-migrated schema.

One row per document, not one row per skill atom: these are read whole
(`get_baseline()` and `load_vocabulary()` already return entire lists), so
per-atom rows would be a schema pretending to be a document store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from services.portfolio.db import Base


# Document kinds. Each is a whole JSON document the operator edits.
KIND_CV = "cv"
KIND_SKILL_BANK = "skill_bank"
KIND_JD_VOCABULARY = "jd_vocabulary"

DOCUMENT_KINDS = (KIND_CV, KIND_SKILL_BANK, KIND_JD_VOCABULARY)


class DocumentRow(Base):
    """A versioned document owned by one tenant (CV, skill bank, vocabulary).

    ``(tenant_id, kind)`` is unique: one current row per document *per
    tenant*, where a tenant is a user id. ``version`` increments on every
    write so an edit is traceable, replacing the `git log` that the
    file-based bank used to provide.
    """

    __tablename__ = "operator_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", name="uq_operator_documents_tenant_kind"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Deleting a user takes their documents with them; nothing else can
    # meaningfully own them.
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
