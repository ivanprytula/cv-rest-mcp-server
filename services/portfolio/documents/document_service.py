"""Operator document service: file-only for api-core without DB.

Reads operator documents (CV, skill bank, JD vocabulary) from local JSON files.
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
    """Reads operator documents from local files."""

    def __init__(self, repo: DocumentRepository) -> None:
        self._repo = repo

    async def read(
        self, kind: str, *, tenant_id: int, fallback_path: Path | None = None
    ) -> dict[str, Any] | None:
        """Return one tenant's document from the file fallback."""
        try:
            row = await self._repo.get(kind, tenant_id=tenant_id)
        except Exception:
            logger.warning("Document %s unreadable from repo", kind, exc_info=True)
            row = None
        if row is not None:
            return row.get("payload")

        if fallback_path is None:
            return None
        try:
            return json.loads(fallback_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):  # fmt: skip
            logger.warning(
                "Document %s has no DB row and no usable file at %s",
                kind,
                fallback_path,
            )
            return None

    async def write(
        self, kind: str, payload: dict[str, Any], *, tenant_id: int
    ) -> int | None:
        """Not supported in file-only mode."""
        return None

    async def revert_to_file(self, kind: str, *, tenant_id: int) -> bool:
        """Not supported in file-only mode."""
        return False

    async def versions(self, *, tenant_id: int) -> dict[str, int]:
        """Not supported in file-only mode."""
        return {}

    async def seed_from_files(
        self, sources: dict[str, Path], *, tenant_id: int
    ) -> None:
        """Not supported in file-only mode."""
        pass


def document_sources(settings: Any) -> dict[str, Path]:
    """Map each document kind to the file that seeds and backs it."""
    return {
        KIND_CV: settings.cv_data_path,
        KIND_SKILL_BANK: settings.cv_baseline_path,
        KIND_JD_VOCABULARY: settings.jd_vocabulary_path,
    }
