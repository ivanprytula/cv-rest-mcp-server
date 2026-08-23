import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from app.settings import Settings


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


class Skill(BaseModel):
    category: str = ""
    items: list[str] = []


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
    summary: str = ""
    skills: list[Skill] = []
    additional_skills: list[Skill] = []
    experience: list[Experience] = []
    education: list[Education] = []
    languages: list[str] = []
    projects: list[Project] = []
    certifications: list[Certification] = []
    publications: list[Publication] = []
    awards: list[Award] = []
    volunteering: list[Volunteering] = []


def load_cv_data(path: Path | None = None) -> dict:
    file_path = path or Settings().cv_data_path

    if not file_path.exists():
        raise FileNotFoundError(
            f"CV data file not found: {file_path}. Set CV_DATA_PATH or create data/cv.json."
        )

    with file_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

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


CV_DATA = load_cv_data()
