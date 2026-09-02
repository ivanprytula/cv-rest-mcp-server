"""Request/response schemas for the CV tailor endpoints."""

from pydantic import BaseModel


class TailorRequest(BaseModel):
    jd_text: str
    title: str = ""
