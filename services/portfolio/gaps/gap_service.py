"""Gap analysis application service.

Constructed once in `main.py`'s lifespan (`app.state.gap_service`), reached
by routes via `dependencies.get_gap_service`.

Degrade-don't-crash (mirrors `RevisionService`): a Postgres error logs a
warning and returns `None`/`[]` rather than raising. A transient DB hiccup
must never 500 the roadmap page.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from services.portfolio.gaps.gap_repository import GapRepository
from services.portfolio.gaps.job_posting import (
    JobPosting,
    JobPostingSummary,
    RoadmapItem,
)
from services.portfolio.gaps.job_posting_row import JdAnalysisRow, JobPostingRow
from services.portfolio.matching.gap import GapReport, detect_gaps


logger = logging.getLogger(__name__)

# Bump when the vocabulary or extraction logic changes, so the roadmap never
# mixes extractor generations. Re-analysis: bump, re-run, query the new value.
ANALYZER_VERSION = "1"

# Tiers the roadmap ranks. "covered" is excluded: it is what the operator
# already has, and the page answers "what should I learn next?".
ROADMAP_TIERS = ["unvouched", "deferred", "unknown"]


def content_hash(jd_text: str) -> str:
    """SHA-256 hex digest of the JD text, for dedup (not a secret)."""
    return hashlib.sha256(jd_text.encode("utf-8")).hexdigest()


class GapService:
    """Orchestrates posting storage and gap analysis.

    Depends on the `GapRepository` Protocol, not a concrete implementation.
    The analysis itself lives in `matching/gap.py` as pure functions; this
    service only handles persistence and the domain mapping.
    """

    def __init__(self, repo: GapRepository) -> None:
        self._repo = repo

    async def store_posting(
        self,
        *,
        jd_text: str,
        source: str = "manual",
        external_id: str | None = None,
        company: str = "",
        title: str = "",
        url: str = "",
        raw_payload: dict[str, Any] | None = None,
    ) -> tuple[JobPosting | None, bool]:
        """Persist a posting, returning it and whether it already existed.

        Re-pasting the same text returns the stored posting rather than a
        duplicate row — the caller reports it as `duplicate: true`.

        `first_seen_at`/`last_seen_at` are set explicitly rather than left to
        the ORM `default=`: the session uses `expire_on_commit=False`, so the
        row is never reloaded after INSERT and a client-side default would
        leave `to_domain()` reading `None`.
        """
        digest = content_hash(jd_text)
        try:
            existing = await self._repo.find_by_content_hash(digest)
        except Exception:
            logger.warning("Failed to check for duplicate posting", exc_info=True)
            existing = None
        if existing is not None:
            return existing.to_domain(), True

        now = datetime.now(UTC)
        row = JobPostingRow(
            source=source,
            external_id=external_id,
            company=company,
            title=title,
            url=url,
            jd_text=jd_text,
            content_hash=digest,
            raw_payload=raw_payload or {},
            first_seen_at=now,
            last_seen_at=now,
        )
        try:
            stored = await self._repo.upsert_posting(posting=row)
        except Exception:
            logger.warning("Failed to persist job posting", exc_info=True)
            return None, False
        return stored.to_domain(), False

    async def get_posting(self, posting_id: int) -> JobPosting | None:
        try:
            row = await self._repo.get_posting(posting_id)
        except Exception:
            logger.warning("Failed to read posting %s", posting_id, exc_info=True)
            return None
        return row.to_domain() if row else None

    async def list_postings(self) -> list[JobPostingSummary]:
        try:
            rows = await self._repo.list_postings()
        except Exception:
            logger.warning("Failed to list postings", exc_info=True)
            return []
        return [JobPostingSummary.model_validate(row) for row in rows]

    async def analyze_posting(
        self,
        posting_id: int,
        *,
        bank_atoms: list[dict[str, Any]],
        deferred_atoms: list[dict[str, Any]],
        vocabulary: list[dict[str, Any]],
        live_cv: dict[str, Any],
    ) -> GapReport | None:
        """Analyse a stored posting and persist the result.

        Returns None when the posting is missing or a DB error occurs. The
        write is an upsert on (posting_id, analyzer_version), so re-analyzing
        is idempotent.
        """
        posting = await self.get_posting(posting_id)
        if posting is None:
            return None

        report = detect_gaps(
            posting.jd_text, bank_atoms, deferred_atoms, vocabulary, live_cv
        )
        row = JdAnalysisRow(
            posting_id=posting_id,
            analyzer_version=ANALYZER_VERSION,
            result={"gaps": [asdict(gap) for gap in report.gaps]},
            created_at=datetime.now(UTC),
        )
        try:
            await self._repo.save_analysis(analysis=row)
        except Exception:
            logger.warning(
                "Failed to persist analysis for posting %s", posting_id, exc_info=True
            )
            return None
        return report

    async def get_analysis(self, posting_id: int) -> GapReport | None:
        """Read a stored analysis at the current analyzer version."""
        try:
            row = await self._repo.get_analysis(posting_id, ANALYZER_VERSION)
        except Exception:
            logger.warning("Failed to read analysis %s", posting_id, exc_info=True)
            return None
        if row is None:
            return None
        return _report_from_result(row.result)

    async def build_roadmap(self) -> list[RoadmapItem]:
        """Rank gap terms by how many postings demand them.

        `jd_count` descending is the product: the first row is what to learn
        next.
        """
        try:
            rows = await self._repo.aggregate_roadmap(
                analyzer_version=ANALYZER_VERSION, tiers=ROADMAP_TIERS
            )
        except Exception:
            logger.warning("Failed to aggregate roadmap", exc_info=True)
            return []
        return [RoadmapItem(**row) for row in rows]


def _report_from_result(result: dict[str, Any]) -> GapReport:
    """Rebuild a GapReport from its stored JSONB form."""
    from services.portfolio.matching.gap import SkillGap

    return GapReport(gaps=tuple(SkillGap(**gap) for gap in result.get("gaps", [])))
