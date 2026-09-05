"""Job-posting ORM rows — persistence layer, Alembic-migrated schema."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from services.portfolio.db import Base
from services.portfolio.gaps.job_posting import JobPosting


class JobPostingRow(Base):
    """One job description. Postgres-only (`JSONB`), like `RevisionRow`.

    ``first_seen_at``/``last_seen_at`` are the whole "market shift over
    time" model: "new this week" is a filter on the former, "still open" is
    ``closed_at IS NULL``. A per-sighting history table would buy nothing a
    single operator reads.
    """

    __tablename__ = "job_postings"
    __table_args__ = (
        # Portal ids are unique per source; pasted postings have none, and
        # Postgres treats NULLs as distinct so they never collide.
        UniqueConstraint("source", "external_id", name="uq_job_postings_source_ext"),
        Index("ix_job_postings_content_hash", "content_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    jd_text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Nullable and unenforced: multi-tenancy is deferred, but adding the
    # column at table creation costs nothing and saves a backfill later.
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def to_domain(self) -> JobPosting:
        return JobPosting(
            id=self.id,
            source=self.source,
            company=self.company,
            title=self.title,
            url=self.url,
            jd_text=self.jd_text,
            content_hash=self.content_hash,
            first_seen_at=self.first_seen_at,
            last_seen_at=self.last_seen_at,
            closed_at=self.closed_at,
        )


class JdAnalysisRow(Base):
    """A gap analysis of one posting at one analyzer version.

    ``analyzer_version`` earns its place: the vocabulary and extractor will
    change, and without it the roadmap silently mixes generations — you
    could never tell whether "Kafka in 4 postings" means 4 mention it or 4
    were analyzed after "kafka" entered the vocabulary. Re-analysis is an
    upsert on (posting_id, analyzer_version), so it is idempotent.
    """

    __tablename__ = "jd_analyses"
    __table_args__ = (
        UniqueConstraint(
            "posting_id", "analyzer_version", name="uq_jd_analyses_posting_version"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    posting_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("job_postings.id", ondelete="CASCADE"), index=True
    )
    analyzer_version: Mapped[str] = mapped_column(String(32), index=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
