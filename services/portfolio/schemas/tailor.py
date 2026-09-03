"""Request/response schemas for the CV tailor endpoints."""

from pydantic import BaseModel


class TailorRequest(BaseModel):
    jd_text: str
    title: str = ""


class RevisionSummary(BaseModel):
    """One tailored CV revision as listed by GET /api/v1/revisions.

    `id` is the stable selector for `?tailored=`/`saved_to`; `name` is a
    human-readable, timestamp-derived label for display only (the
    operator's revision browser lists many of these).
    """

    id: str
    name: str
    created_at: str  # ISO 8601 UTC
    size_bytes: int
