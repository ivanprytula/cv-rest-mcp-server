"""Operator document service: DB-first, file-on-miss.

The live CV, skill bank and JD vocabulary are operator-edited documents.
They live in Postgres so they can be edited through the API and versioned,
but every read falls back to the on-disk JSON when the DB has no row or is
unreachable.

That fallback is the point, not a nicety: without it `just dev-local` would
need Postgres running to render a CV at all, and a transient DB error would
take down CV rendering entirely. Same degrade-don't-crash posture as
`RevisionService` and `CvSource`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.portfolio.documents.document_repository import DocumentRepository
from services.portfolio.documents.document_row import (
    KIND_CV,
    KIND_JD_VOCABULARY,
    KIND_SKILL_BANK,
)


logger = logging.getLogger(__name__)


class DocumentService:
    """Reads and writes operator documents, degrading to files on any miss.

    Depends on the `DocumentRepository` Protocol, not a concrete adapter.
    """

    def __init__(self, repo: DocumentRepository) -> None:
        self._repo = repo

    async def read(
        self, kind: str, *, fallback_path: Path | None = None
    ) -> dict[str, Any] | None:
        """Return a document: the DB row, else the file, else None.

        A DB error is logged and treated as a miss — the file answer is
        better than an exception.
        """
        try:
            row = await self._repo.get(kind)
        except Exception:
            logger.warning("Document %s unreadable from Postgres", kind, exc_info=True)
            row = None
        if row is not None:
            return row.payload

        if fallback_path is None:
            return None
        try:
            return json.loads(fallback_path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            logger.warning(
                "Document %s has no DB row and no usable file at %s",
                kind,
                fallback_path,
            )
            return None

    async def write(self, kind: str, payload: dict[str, Any]) -> int | None:
        """Store a document, returning its new version (None on failure)."""
        try:
            row = await self._repo.put(kind=kind, payload=payload)
        except Exception:
            logger.warning("Failed to write document %s", kind, exc_info=True)
            return None
        return row.version

    async def revert_to_file(self, kind: str) -> bool:
        """Drop the stored document so reads fall back to the shipped file.

        Named for the effect, not the mechanism: the document does not
        disappear — the next read serves the JSON file instead. That is the
        undo for a bad edit, without hand-restoring the previous payload.
        """
        try:
            return await self._repo.delete(kind)
        except Exception:
            logger.warning("Failed to revert document %s", kind, exc_info=True)
            return False

    async def versions(self) -> dict[str, int]:
        """Current version per stored document kind."""
        try:
            rows = await self._repo.list_all()
        except Exception:
            logger.warning("Failed to list documents", exc_info=True)
            return {}
        return {row.kind: row.version for row in rows}

    async def seed_from_files(self, sources: dict[str, Path]) -> None:
        """Import each file into the DB if that document has no row yet.

        Idempotent: an existing row is never overwritten, so a redeploy does
        not clobber edits made through the API. Runs in the app lifespan,
        alongside `seed_first_admin_from_settings`.
        """
        for kind, path in sources.items():
            try:
                if await self._repo.get(kind) is not None:
                    continue
                payload = json.loads(path.read_text(encoding="utf-8"))
            except OSError, json.JSONDecodeError:
                logger.info("No seed file for document %s at %s; skipping", kind, path)
                continue
            except Exception:
                logger.warning(
                    "Could not check document %s for seeding", kind, exc_info=True
                )
                continue
            if await self.write(kind, payload) is not None:
                logger.info("Seeded document %s from %s", kind, path)


def document_sources(settings: Any) -> dict[str, Path]:
    """Map each document kind to the file that seeds and backs it."""
    return {
        KIND_CV: settings.cv_data_path,
        KIND_SKILL_BANK: settings.cv_baseline_path,
        KIND_JD_VOCABULARY: settings.jd_vocabulary_path,
    }
