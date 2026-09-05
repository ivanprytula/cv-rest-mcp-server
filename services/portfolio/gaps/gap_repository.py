"""Gap repository — port (Protocol) + the one concrete adapter.

`GapService` depends on the `GapRepository` Protocol, not the SQLAlchemy
adapter, mirroring `revisions/revision_repository.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select, text
from sqlalchemy import true as sa_true
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.portfolio.gaps.job_posting_row import (
    AtsBoardRow,
    JdAnalysisRow,
    JobPostingRow,
)


# Aggregates the roadmap straight out of the analyses' JSONB. Recomputed per
# request: at a few hundred postings this is milliseconds, so a materialised
# view would only add a staleness bug.
# ponytail: plain query; add a cache when it stops being instant.
_ROADMAP_SQL = text("""
    SELECT
        gap->>'term'                              AS term,
        gap->>'tier'                              AS tier,
        COALESCE(gap->>'group_id', '')            AS group_id,
        COUNT(DISTINCT a.posting_id)              AS jd_count,
        -- Rank by level STRENGTH, not alphabetically: a plain MAX() over
        -- basic/expert/middle returns 'middle', so a JD demanding expert
        -- would be reported as middle.
        (ARRAY[NULL, 'basic', 'middle', 'expert'])[
            MAX(CASE gap->>'required_level'
                    WHEN 'expert' THEN 4
                    WHEN 'middle' THEN 3
                    WHEN 'basic'  THEN 2
                    ELSE 1
                END)
        ]                                         AS strongest_level_asked,
        MAX(gap->>'note')                         AS note
    FROM jd_analyses AS a
    CROSS JOIN LATERAL jsonb_array_elements(a.result->'gaps') AS gap
    WHERE a.analyzer_version = :version
      AND gap->>'tier' = ANY(:tiers)
    GROUP BY 1, 2, 3
    ORDER BY jd_count DESC, term ASC
""")


class GapRepository(Protocol):
    async def upsert_posting(self, *, posting: JobPostingRow) -> JobPostingRow: ...
    async def get_posting(self, posting_id: int) -> JobPostingRow | None: ...
    async def find_by_content_hash(self, content_hash: str) -> JobPostingRow | None: ...
    async def find_by_source_external_id(
        self, source: str, external_id: str
    ) -> JobPostingRow | None: ...
    async def list_postings(
        self, *, mentions_term: str | None = None, analyzer_version: str = ""
    ) -> list[JobPostingRow]: ...
    async def close_missing_postings(
        self, *, source: str, company_slug: str, seen_external_ids: set[str]
    ) -> int: ...
    async def save_analysis(self, *, analysis: JdAnalysisRow) -> JdAnalysisRow: ...
    async def get_analysis(
        self, posting_id: int, analyzer_version: str
    ) -> JdAnalysisRow | None: ...
    async def aggregate_roadmap(
        self, *, analyzer_version: str, tiers: list[str]
    ) -> list[dict[str, Any]]: ...
    async def get_board(self, source: str, company_slug: str) -> AtsBoardRow | None: ...
    async def upsert_board(
        self, *, source: str, company_slug: str, etag: str | None
    ) -> AtsBoardRow: ...


class SqlAlchemyGapRepository:
    """Async SQLAlchemy gap repository (Postgres, `asyncpg`).

    Takes the shared `async_sessionmaker` built once in `main.py`'s lifespan,
    not its own engine — same rationale as `SqlAlchemyRevisionRepository`.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_posting(self, *, posting: JobPostingRow) -> JobPostingRow:
        """Insert a posting, or bump `last_seen_at` if the portal already sent it.

        Keyed on (source, external_id). A pasted posting has no external id,
        so it always inserts — dedup for those is the caller's job via
        `content_hash`.
        """
        if posting.external_id is None:
            async with self._session_factory() as session:
                session.add(posting)
                await session.commit()
            return posting

        values = {
            column.name: getattr(posting, column.name)
            for column in JobPostingRow.__table__.columns
            if column.name != "id" and getattr(posting, column.name) is not None
        }
        stmt = (
            insert(JobPostingRow)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_job_postings_source_ext",
                set_={
                    "last_seen_at": values["last_seen_at"],
                    "jd_text": values["jd_text"],
                    "content_hash": values["content_hash"],
                    "raw_payload": values["raw_payload"],
                    "closed_at": None,
                },
            )
            .returning(JobPostingRow)
        )
        async with self._session_factory() as session:
            row = (await session.execute(stmt)).scalar_one()
            await session.commit()
            return row

    async def get_posting(self, posting_id: int) -> JobPostingRow | None:
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(JobPostingRow).where(JobPostingRow.id == posting_id)
                )
            ).scalar_one_or_none()

    async def find_by_content_hash(self, content_hash: str) -> JobPostingRow | None:
        """Find an existing posting with identical text (re-paste dedup)."""
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(JobPostingRow)
                    .where(JobPostingRow.content_hash == content_hash)
                    .order_by(JobPostingRow.id)
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def find_by_source_external_id(
        self, source: str, external_id: str
    ) -> JobPostingRow | None:
        """Find a portal-sourced posting by its stable board identity.

        Used to detect whether an ATS-fetched posting's text changed since
        last sync — the board identity stays fixed even when a company edits
        the JD, so content_hash alone can't answer "is this the same posting".
        """
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(JobPostingRow).where(
                        JobPostingRow.source == source,
                        JobPostingRow.external_id == external_id,
                    )
                )
            ).scalar_one_or_none()

    async def close_missing_postings(
        self, *, source: str, company_slug: str, seen_external_ids: set[str]
    ) -> int:
        """Mark open postings from this board absent from the current fetch as closed.

        One UPDATE per board per refresh, not a per-row diff in Python — the
        board's full current listing is the source of truth for "still open".
        An empty `seen_external_ids` closes every open posting on the board
        (a legitimate outcome: the board itself may have gone empty), so the
        caller must not call this after a failed/partial fetch.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                sa_update(JobPostingRow)
                .where(
                    JobPostingRow.source == source,
                    JobPostingRow.company_slug == company_slug,
                    JobPostingRow.closed_at.is_(None),
                    JobPostingRow.external_id.is_not(None),
                    JobPostingRow.external_id.not_in(seen_external_ids)
                    if seen_external_ids
                    else sa_true(),
                )
                .values(closed_at=datetime.now(UTC))
                .returning(JobPostingRow.id)
            )
            closed_ids = result.scalars().all()
            await session.commit()
            return len(closed_ids)

    async def list_postings(
        self, *, mentions_term: str | None = None, analyzer_version: str = ""
    ) -> list[JobPostingRow]:
        """List postings, newest first, optionally filtered by a mentioned term.

        `mentions_term` matches any tier (covered/stale/unvouched/deferred/
        unknown all mean "the JD asked for this"; only *how confidently the
        CV covers it* differs). Case-insensitive exact match on the stored
        `SkillGap.term` — that field already holds the canonical bank/
        vocabulary name, not raw JD text, so `ILIKE`-style partial matching
        would risk cross-matching unrelated terms sharing a substring.
        Postings never analyzed at `analyzer_version` are excluded, same as
        the roadmap: an unanalyzed posting can't confirm or deny a mention.
        Callers passing `mentions_term` must also pass the current
        `analyzer_version` (no meaningful default — an empty string matches
        no row, degrading to an empty result rather than raising).
        """
        if mentions_term is None:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(JobPostingRow).order_by(JobPostingRow.first_seen_at.desc())
                )
                return list(result.scalars().all())

        # The `jsonb_array_elements` lateral unnest has no ORM-level
        # expression, so the match itself is raw SQL (same pattern as
        # `_ROADMAP_SQL` above) — but hydration goes through a normal
        # `select(JobPostingRow)` keyed on the matched ids, so callers get
        # real ORM instances rather than a hand-built row.
        matching_ids_stmt = text("""
            SELECT DISTINCT p.id
            FROM job_postings AS p
            JOIN jd_analyses AS a ON a.posting_id = p.id
            CROSS JOIN LATERAL jsonb_array_elements(a.result->'gaps') AS gap
            WHERE a.analyzer_version = :version
              AND lower(gap->>'term') = lower(:term)
        """)
        async with self._session_factory() as session:
            id_rows = await session.execute(
                matching_ids_stmt, {"version": analyzer_version, "term": mentions_term}
            )
            matching_ids = [row.id for row in id_rows]
            if not matching_ids:
                return []
            result = await session.execute(
                select(JobPostingRow)
                .where(JobPostingRow.id.in_(matching_ids))
                .order_by(JobPostingRow.first_seen_at.desc())
            )
            return list(result.scalars().all())

    async def save_analysis(self, *, analysis: JdAnalysisRow) -> JdAnalysisRow:
        """Store an analysis, replacing any prior run at the same version."""
        stmt = (
            insert(JdAnalysisRow)
            .values(
                posting_id=analysis.posting_id,
                analyzer_version=analysis.analyzer_version,
                result=analysis.result,
                created_at=analysis.created_at,
            )
            .on_conflict_do_update(
                constraint="uq_jd_analyses_posting_version",
                set_={"result": analysis.result, "created_at": analysis.created_at},
            )
            .returning(JdAnalysisRow)
        )
        async with self._session_factory() as session:
            row = (await session.execute(stmt)).scalar_one()
            await session.commit()
            return row

    async def get_analysis(
        self, posting_id: int, analyzer_version: str
    ) -> JdAnalysisRow | None:
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(JdAnalysisRow).where(
                        JdAnalysisRow.posting_id == posting_id,
                        JdAnalysisRow.analyzer_version == analyzer_version,
                    )
                )
            ).scalar_one_or_none()

    async def aggregate_roadmap(
        self, *, analyzer_version: str, tiers: list[str]
    ) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            result = await session.execute(
                _ROADMAP_SQL, {"version": analyzer_version, "tiers": tiers}
            )
            return [dict(row) for row in result.mappings()]

    async def get_board(self, source: str, company_slug: str) -> AtsBoardRow | None:
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(AtsBoardRow).where(
                        AtsBoardRow.source == source,
                        AtsBoardRow.company_slug == company_slug,
                    )
                )
            ).scalar_one_or_none()

    async def upsert_board(
        self, *, source: str, company_slug: str, etag: str | None
    ) -> AtsBoardRow:
        """Record a board's fetch, replacing its prior etag/timestamp."""
        stmt = (
            insert(AtsBoardRow)
            .values(
                source=source,
                company_slug=company_slug,
                etag=etag,
                last_fetched_at=datetime.now(UTC),
            )
            .on_conflict_do_update(
                constraint="uq_ats_boards_source_slug",
                set_={"etag": etag, "last_fetched_at": datetime.now(UTC)},
            )
            .returning(AtsBoardRow)
        )
        async with self._session_factory() as session:
            row = (await session.execute(stmt)).scalar_one()
            await session.commit()
            return row
