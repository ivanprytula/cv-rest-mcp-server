"""Tracked-board domain entity — no framework or DB imports.

Mirrors `job_posting.py`'s layering: a plain Pydantic model the service layer
returns, built from the ORM row via `to_domain()`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TrackedBoard(BaseModel):
    """One tracked company: an API-backed ATS board, or a career-page URL."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    company_name: str
    company_slug: str | None = None
    url: str | None = None
    notes: str | None = None
    group: str | None = None
    active: bool
    created_at: datetime
    updated_at: datetime
