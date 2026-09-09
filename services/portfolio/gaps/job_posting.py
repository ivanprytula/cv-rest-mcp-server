"""Job-posting domain entities — no framework or DB imports.

Plain Pydantic models the service layer returns, built from ORM rows via
`to_domain()`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobPosting(BaseModel):
    """One job description, however it arrived (pasted or fetched)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    company: str
    title: str
    url: str
    posting_text: str
    content_hash: str
    first_seen_at: datetime
    last_seen_at: datetime
    closed_at: datetime | None = None


class JobPostingSummary(BaseModel):
    """A posting without its text — what the list endpoint returns."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    company: str
    title: str
    url: str
    first_seen_at: datetime
    last_seen_at: datetime
    closed_at: datetime | None = None


class RoadmapItem(BaseModel):
    """One term, ranked by how many postings demand it.

    ``posting_count`` sorted descending is the product: "Kubernetes — 12 of 20
    postings — learn first". Everything else is supporting detail.
    """

    term: str
    tier: str
    group_id: str
    posting_count: int
    strongest_level_asked: str | None = None
    note: str | None = None


class PhraseCluster(BaseModel):
    """One group of paraphrased responsibility sentences from a posting.

    ``label`` is the medoid phrase — a real JD sentence closest, on average,
    to every other phrase in its own cluster — not an LLM summary.
    """

    label: str
    phrases: list[str]
