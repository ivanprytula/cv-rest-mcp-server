"""Request/response models for the gap-analysis API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.portfolio.gaps.job_posting import JobPostingSummary, RoadmapItem


class SkillGapOut(BaseModel):
    """One JD requirement and the tier it resolved to."""

    term: str
    tier: str
    group_id: str
    required_level: str | None = None
    bank_level: str | None = None
    note: str | None = None
    evidence: str = ""


class GapReportOut(BaseModel):
    """A posting's requirements, split by tier."""

    posting_id: int
    coverage: float = Field(description="Share of requirements already on the CV")
    gaps: list[SkillGapOut]


class PostingCreated(BaseModel):
    """Result of storing a posting."""

    id: int
    content_hash: str
    duplicate: bool = Field(
        default=False, description="True when this text was already stored"
    )


class PostingList(BaseModel):
    postings: list[JobPostingSummary]


class LearningRoadmap(BaseModel):
    """Gap terms ranked by how many postings demand them."""

    items: list[RoadmapItem]
    analyzer_version: str
