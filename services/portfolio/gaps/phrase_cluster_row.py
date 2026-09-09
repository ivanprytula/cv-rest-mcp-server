"""Phrase-cluster ORM rows — persistence layer, Alembic-migrated schema.

Two tables: `phrase_embeddings` caches one vector per unique phrase (keyed by
content hash, so re-analyzing a posting never re-embeds unchanged sentences),
and `phrase_clusters` records which phrases the last clustering run grouped
together, for one posting at a time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from services.portfolio.db import Base


class PhraseEmbeddingRow(Base):
    """One cached embedding, keyed by the phrase's content hash.

    Embedding the same responsibility sentence across many postings (a
    common phrase like "Led cross-functional collaboration" recurs a lot)
    would otherwise re-run the model for text already seen.
    """

    __tablename__ = "phrase_embeddings"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    phrase: Mapped[str] = mapped_column(Text)
    vector: Mapped[list[float]] = mapped_column(JSONB)
    model_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class PhraseClusterRow(Base):
    """One clustering run's groups for one posting.

    Re-clustering a posting (new threshold, more phrases) replaces its prior
    row rather than accumulating runs — nothing here is aggregated across
    postings the way `posting_analyses` feeds the roadmap, so there is no
    versioning concern to preserve history for.
    """

    __tablename__ = "phrase_clusters"
    __table_args__ = (
        UniqueConstraint("posting_id", name="uq_phrase_clusters_posting"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    posting_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("job_postings.id", ondelete="CASCADE"), index=True
    )
    # [{"label": "<medoid phrase>", "phrases": ["...", "..."]}, ...]
    clusters: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    threshold: Mapped[float] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
