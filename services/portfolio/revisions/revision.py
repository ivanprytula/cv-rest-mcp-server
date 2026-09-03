"""Tailored CV revision domain layer (ADR-023) — no framework/DB imports.

`Revision` is the identity the rest of the system sees; `RevisionRow`
(persistence) maps onto it via `.to_domain()`. Mirrors `auth/user.py`'s
layering.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Revision(BaseModel):
    """Domain entity — one tailored CV snapshot written by POST /api/v1/cv/tailor.

    `id` is the stable public selector (`?tailored=<id>`, `saved_to`); `name`
    is a human-readable, timestamp-derived label for display only (the
    operator's revision browser lists many of these — an id-only list is
    unreadable). `tailored_cv` is the full CV payload as tailored.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    jd_hash: str
    tailored_cv: dict
    promoted: bool = False
