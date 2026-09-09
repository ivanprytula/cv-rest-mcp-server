"""Tracked-board application service.

Constructed once in the app's lifespan (`app.state.tracked_board_service`),
reached by routes via `dependencies.get_tracked_board_service`.

Degrade-don't-crash (mirrors `GapService`/`DocumentService`): a Postgres
error logs a warning and returns `None`/`[]`/`False` rather than raising.
"""

from __future__ import annotations

import logging
from typing import Any

from services.portfolio.gaps.tracked_board_repository import TrackedBoardRepository
from services.portfolio.gaps.tracked_board_row import (
    ALL_KINDS,
    API_BACKED_KINDS,
    KIND_URL_ONLY,
    TrackedBoardRow,
)


logger = logging.getLogger(__name__)


class TrackedBoardValidationError(ValueError):
    """A create/update payload violates the kind/field rule."""


def _validate_create_fields(
    *, kind: str, company_slug: str | None, url: str | None
) -> None:
    """Enforce the kind/field rule before anything reaches the DB.

    API-backed kinds (greenhouse/lever/ashby) identify a board by
    `company_slug` on that portal and never have a `url`; `url_only` is the
    reverse — a career-page URL with no *registered fetcher* yet, regardless
    of whether that URL turns out to have its own JSON API, needs HTML
    scraping, or redirects to a third-party recruiting agency's page —
    `notes` is where an operator can jot that kind of observation until a
    fetcher for it exists. Kind is immutable once created (see
    `TrackedBoardService.update`'s `fields` contract), so this is the only
    place the rule is ever checked.
    """
    if kind not in ALL_KINDS:
        raise TrackedBoardValidationError(
            f"Unknown board kind {kind!r}; expected one of {ALL_KINDS}"
        )
    if kind in API_BACKED_KINDS:
        if not company_slug:
            raise TrackedBoardValidationError(
                f"Board kind {kind!r} requires company_slug"
            )
        if url:
            raise TrackedBoardValidationError(f"Board kind {kind!r} must not set url")
    elif kind == KIND_URL_ONLY:
        if not url:
            raise TrackedBoardValidationError("url_only board requires url")
        if company_slug:
            raise TrackedBoardValidationError(
                "url_only board must not set company_slug"
            )


class TrackedBoardService:
    """Manages the registry of tracked boards.

    Depends on the `TrackedBoardRepository` Protocol, not a concrete
    implementation, mirroring `GapService`.
    """

    def __init__(self, repo: TrackedBoardRepository) -> None:
        self._repo = repo

    async def create(
        self,
        *,
        kind: str,
        company_name: str,
        company_slug: str | None,
        url: str | None,
        notes: str | None = None,
        group: str | None = None,
    ) -> TrackedBoardRow:
        """Create a tracked board. Raises `TrackedBoardValidationError` on a
        malformed kind/field combination — validated before any DB write."""
        _validate_create_fields(kind=kind, company_slug=company_slug, url=url)
        return await self._repo.create(
            kind=kind,
            company_name=company_name,
            company_slug=company_slug,
            url=url,
            notes=notes,
            group=group,
        )

    async def list_all(
        self, *, active_only: bool = True, group: str | None = None
    ) -> list[TrackedBoardRow]:
        """`group=None` means every group (today's default). To scope a
        refresh trigger run to one group, pass its name explicitly — there
        is no separate way to select "boards with no group at all"; that
        wasn't asked for and isn't built speculatively."""
        try:
            return await self._repo.list_all(active_only=active_only, group=group)
        except Exception:
            logger.warning("Failed to list tracked boards", exc_info=True)
            return []

    async def get(self, board_id: int) -> TrackedBoardRow | None:
        try:
            return await self._repo.get(board_id)
        except Exception:
            logger.warning("Failed to read tracked board %s", board_id, exc_info=True)
            return None

    async def update(
        self, board_id: int, fields: dict[str, Any]
    ) -> TrackedBoardRow | None:
        """Partially update a board. `fields` never contains `kind` — the
        schema layer (`TrackedBoardUpdate`) has no such field at all, since
        kind is immutable once created (switch kinds via delete + re-create)."""
        try:
            return await self._repo.update(board_id, fields)
        except Exception:
            logger.warning("Failed to update tracked board %s", board_id, exc_info=True)
            return None

    async def delete(self, board_id: int) -> bool:
        try:
            return await self._repo.delete(board_id)
        except Exception:
            logger.warning("Failed to delete tracked board %s", board_id, exc_info=True)
            return False
