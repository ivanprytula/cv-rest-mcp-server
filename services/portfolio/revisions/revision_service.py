"""Revision application service (ADR-023).

Construction happens once in `main.py`'s lifespan (`app.state.revision_service`),
matching `UserService`/`PdfService`. Routes reach it via FastAPI's `Depends`
(`services.portfolio.dependencies.get_revision_service`).

Degrade-don't-crash (mirrors `CvSource`): a Postgres error on any operation
logs a warning and returns `None`/`[]` rather than raising, so a transient DB
hiccup never 500s the tailoring endpoint — the caller (routes.py) falls back
to the file-glob path on `None`/empty.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from services.portfolio.revisions.revision import Revision
from services.portfolio.revisions.revision_repository import RevisionRepository
from services.portfolio.revisions.revision_row import RevisionRow


logger = logging.getLogger(__name__)


def jd_hash(jd_text: str) -> str:
    """SHA-256 hex digest of the JD text, for dedup/audit (not a secret)."""
    return hashlib.sha256(jd_text.encode("utf-8")).hexdigest()


class RevisionService:
    """Application service orchestrating the revision repo.

    Depends on the `RevisionRepository` Protocol, not a concrete
    implementation — the seam for swapping in a different repo without
    touching callers.
    """

    def __init__(self, repo: RevisionRepository) -> None:
        self._repo = repo

    async def create(self, *, jd_text: str, tailored_cv: dict) -> Revision | None:
        """Persist a tailored CV revision. Returns None on any DB error
        (caller falls back to the file-glob path) rather than raising.

        `promoted`/`created_at` are set explicitly (not left to the ORM
        column `default=`): `SqlAlchemyRevisionRepository` uses
        `expire_on_commit=False`, so the row `.create()` hands back is never
        reloaded from the server after INSERT — relying on a client-side
        `default=` would leave `.to_domain()` seeing `None` here. `id` is the
        one exception: it's the autoincrement primary key, which Postgres
        always returns via `RETURNING` on INSERT regardless of
        `expire_on_commit`, so it's populated correctly without help.
        """
        stamp = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
        row = RevisionRow(
            name=f"cv_tailored-{stamp}.json",
            jd_hash=jd_hash(jd_text),
            tailored_cv=tailored_cv,
            promoted=False,
            created_at=datetime.now(UTC),
        )
        try:
            created = await self._repo.create(revision=row)
        except Exception:
            logger.warning(
                "Failed to persist tailored revision to Postgres", exc_info=True
            )
            return None
        return created.to_domain()

    async def get_by_id(self, revision_id: int) -> Revision | None:
        try:
            row = await self._repo.get_by_id(revision_id)
        except Exception:
            logger.warning(
                "Failed to read revision %s from Postgres", revision_id, exc_info=True
            )
            return None
        return row.to_domain() if row else None

    async def list_all(self) -> list[Revision]:
        try:
            rows = await self._repo.list_all()
        except Exception:
            logger.warning("Failed to list revisions from Postgres", exc_info=True)
            return []
        return [row.to_domain() for row in rows]
