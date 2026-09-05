"""Gap repository — port (Protocol) + the one concrete adapter.

`GapService` depends on the `GapRepository` Protocol, not the SQLAlchemy
adapter, mirroring `revisions/revision_repository.py`.
"""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.portfolio.gaps.job_posting_row import JdAnalysisRow, JobPostingRow


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
    async def list_postings(self) -> list[JobPostingRow]: ...
    async def save_analysis(self, *, analysis: JdAnalysisRow) -> JdAnalysisRow: ...
    async def get_analysis(
        self, posting_id: int, analyzer_version: str
    ) -> JdAnalysisRow | None: ...
    async def aggregate_roadmap(
        self, *, analyzer_version: str, tiers: list[str]
    ) -> list[dict[str, Any]]: ...


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

    async def list_postings(self) -> list[JobPostingRow]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(JobPostingRow).order_by(JobPostingRow.first_seen_at.desc())
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
