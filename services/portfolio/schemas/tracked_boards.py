"""Request models for the tracked-boards API."""

from __future__ import annotations

from pydantic import BaseModel


class TrackedBoardCreate(BaseModel):
    """A new tracked board: an API-backed ATS source, or a career-page URL.

    `kind` determines which of `company_slug`/`url` is required — enforced
    by `TrackedBoardService.create`, not here, so the same rule the service
    already needs (immutable kind means `update()` must recheck nothing)
    isn't duplicated in two places.
    """

    kind: str
    company_name: str
    company_slug: str | None = None
    url: str | None = None
    notes: str | None = None
    group: str | None = None


class TrackedBoardUpdate(BaseModel):
    """A partial update. No `kind` field at all — immutable once created,
    not merely ignored if sent; switching kinds means delete + re-create."""

    company_name: str | None = None
    company_slug: str | None = None
    url: str | None = None
    notes: str | None = None
    group: str | None = None
    active: bool | None = None
