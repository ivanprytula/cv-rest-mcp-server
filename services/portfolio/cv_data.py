"""CV data models and loaders.

Data is no longer a module global; callers must pass an explicit path
(or use CvSource for file/GCS resolution).
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError


class Experience(BaseModel):
    role: str = ""
    company: str = ""
    period: str = ""
    highlights: list[str] = []
    tech: list[str] = []


class Education(BaseModel):
    degree: str = ""
    institution: str = ""
    year: str = ""


class Project(BaseModel):
    name: str = ""
    description: str = ""
    url: str = ""
    tech: list[str] = []


class Certification(BaseModel):
    name: str = ""
    issuer: str = ""
    date: str = ""
    url: str = ""


class Publication(BaseModel):
    title: str = ""
    venue: str = ""
    year: str = ""
    url: str = ""


class Award(BaseModel):
    name: str = ""
    issuer: str = ""
    date: str = ""


class Volunteering(BaseModel):
    role: str = ""
    organization: str = ""
    period: str = ""
    description: str = ""


class Website(BaseModel):
    name: str = ""
    url: str = ""


class SkillSubCategory(BaseModel):
    """Typed group within a skill category (e.g. 'frameworks' under 'Backend development')."""

    name: str = ""
    items: list[str] = []


class SkillCategory(BaseModel):
    """Top-level skill category with optional typed sub-groups."""

    name: str = ""
    sub_categories: list[SkillSubCategory] = []


class CVData(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = ""
    title: str = ""
    email: str = ""
    phone: str = ""
    telegram: str = ""
    location: str = ""
    github: str = ""
    linkedin: str = ""
    websites: list[Website] = []
    summary: str = ""
    skills: list[SkillCategory] = []
    additional_skills: list[SkillCategory] = []
    experience: list[Experience] = []
    education: list[Education] = []
    languages: list[str] = []
    projects: list[Project] = []
    certifications: list[Certification] = []
    publications: list[Publication] = []
    awards: list[Award] = []
    volunteering: list[Volunteering] = []


def validate_cv_payload(raw) -> dict:
    """Validate and normalize a raw CV JSON object into the canonical dict."""
    if not isinstance(raw, dict):
        raise ValueError(f"CV data must be a JSON object, got {type(raw).__name__}")

    if isinstance(raw.get("education"), dict):
        raw["education"] = [raw["education"]]

    try:
        cv = CVData(**raw)
    except ValidationError as exc:
        lines = ["CV data validation failed:"]
        for error in exc.errors():
            loc = ".".join(str(part) for part in error["loc"])
            lines.append(f"  - {loc}: {error['msg']}")
        lines.append(f"Expected schema: {CVData.model_json_schema()}")
        raise ValueError("\n".join(lines)) from exc

    return cv.model_dump()


def load_cv_data(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"CV data file not found: {path}. Set CV_DATA_PATH or create data/cv.json."
        )

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    return validate_cv_payload(raw)
