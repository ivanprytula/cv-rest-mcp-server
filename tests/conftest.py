import json
import os

import pytest
from httpx import ASGITransport, AsyncClient


os.environ.update(
    {
        "SERVICE_HOURS_START": "",
        "SERVICE_HOURS_END": "",
        "SERVICE_DAYS": "",
        "SERVICE_TIMEZONE": "",
        "ALLOWED_IPS": "",
        "BLOCKED_IPS": "",
        "FAILBAN_THRESHOLD": "0",
        "TRUST_PROXY": "false",
        "CLIENT_IP_XFF_ENTRY": "0",
        "CLIENT_IP_HEADER": "",
        "CV_DATA_PATH": "data/cv.example.json",
        "CV_DATA_GCS_URI": "",
        # Default test token for the tailor auth gate. Tests that exercise
        # the auth middleware itself set this to "" via `set_tailor_token`
        # to assert fail-closed; everything else uses this value.
        "TAILOR_BEARER_TOKEN": "test-token",
    }
)
os.environ.pop("ALLOWED_IPS_FILE", None)
os.environ.pop("BLOCKED_IPS_FILE", None)
os.environ.pop("TAILOR_BEARER_TOKEN_FILE", None)

from app.constants import PDF_CACHE_MAX_ENTRIES, PDF_EXECUTOR_MAX_WORKERS
from app.cv_source import CvSource
from app.dependencies import get_pdf_service
from app.main import app
from app.pdf_generator import PdfService


# Synthetic CV content so tests never depend on data/cv.json wording.
# Assertions in test modules may reference these literals freely.
SYNTHETIC_CV = {
    "name": "Jane Doe",
    "title": "Backend Engineer",
    "email": "jane.doe@example.com",
    "phone": "+00 000 000 000",
    "telegram": "@janedoe",
    "location": "Remote, Testland",
    "github": "https://github.com/janedoe",
    "linkedin": "https://www.linkedin.com/in/janedoe/",
    "summary": "Synthetic summary used by the test suite.",
    "skills": [
        {
            "name": "Testing",
            "sub_categories": [
                {"name": "practices", "items": ["pytest", "fixtures"]},
            ],
        },
    ],
    "experience": [
        {
            "role": "Senior Developer",
            "company": "Beta Corp",
            "period": "01/2023 - 01/2024",
            "highlights": ["Did things", "Did more things"],
            "tech": ["Python", "FastAPI"],
        },
        {
            "role": "Developer",
            "company": "Alpha Corp",
            "period": "01/2021 - 01/2023",
            "highlights": ["Built stuff"],
            "tech": ["Django"],
        },
    ],
    "education": [
        {"degree": "BSc Testing", "institution": "Test University", "year": "2020"},
    ],
    "languages": ["English: C2"],
}


@pytest.fixture
def synthetic_cv():
    return SYNTHETIC_CV


@pytest.fixture
def synthetic_cv_path(tmp_path):
    path = tmp_path / "cv.json"
    path.write_text(json.dumps(SYNTHETIC_CV), encoding="utf-8")
    return path


@pytest.fixture
def pdf_service(synthetic_cv_path):
    return PdfService(
        CvSource(local_path=synthetic_cv_path),
        max_entries=PDF_CACHE_MAX_ENTRIES,
        max_workers=PDF_EXECUTOR_MAX_WORKERS,
    )


@pytest.fixture
def override_pdf_service(pdf_service):
    app.dependency_overrides[get_pdf_service] = lambda: pdf_service
    app.state.pdf_service = pdf_service
    yield pdf_service
    app.dependency_overrides.clear()
    app.state.pdf_service = None


# Default test token for the tailor auth gate. Tests that exercise the
# auth middleware itself clear this via `set_tailor_token("")` to assert
# fail-closed; everything else uses this value. Mirrored in the
# `client` fixture's default Authorization header below.
TAILOR_TEST_TOKEN = "test-token"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {TAILOR_TEST_TOKEN}"},
    ) as ac:
        yield ac


@pytest.fixture
def set_tailor_token(monkeypatch):
    """Set TAILOR_BEARER_TOKEN for the duration of one test.

    Pydantic Settings is mutable (settings are constructed once at import
    time), so we patch the settings instance directly — the same pattern
    `test_guards.py` uses for `allowed_ips` / `service_hours_start`. The
    middleware reads `settings.tailor_bearer_token` at request time, so
    the patched value takes effect immediately. Returns the value so
    tests can re-use it in the Authorization header.
    """

    def _set(value: str) -> str:
        from app.settings import (
            settings,
        )  # local import — module-level import would re-bind

        monkeypatch.setattr(settings, "tailor_bearer_token", value)
        return value

    return _set


# Synthetic skill bank so the tailor pipeline is exercised against a fixed,
# test-owned bank instead of the operator's data/cv_baseline.json.
SYNTHETIC_BASELINE = {
    "_schema_version": "1",
    "skills": [
        {
            "atom": "pytest",
            "group_id": "testing",
            "level": "expert",
            "priority": "high",
            "category_hint": "Testing and quality > practices",
        },
        {
            "atom": "Python",
            "group_id": "backend",
            "level": "expert",
            "priority": "high",
            "category_hint": "Backend development > languages",
        },
        {
            "atom": "FastAPI",
            "group_id": "backend",
            "level": "expert",
            "priority": "high",
            "category_hint": "Backend development > frameworks",
        },
        {
            "atom": "PostgreSQL",
            "group_id": "databases",
            "level": "middle",
            "priority": "medium",
            "category_hint": "Databases and data processing > datastores",
        },
        {
            "atom": "Redis",
            "group_id": "databases",
            "level": "basic",
            "priority": "low",
            "category_hint": "Databases and data processing > datastores",
        },
    ],
}


@pytest.fixture
def synthetic_baseline_path(tmp_path):
    path = tmp_path / "cv_baseline.json"
    path.write_text(json.dumps(SYNTHETIC_BASELINE, indent=2), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def tailor_settings(synthetic_baseline_path, tmp_path, monkeypatch):
    """Point the tailor pipeline at the synthetic bank + a tmp revision dir.

    Autouse so every test is independent of the operator's data/cv_baseline.json
    and no test ever writes a cv_tailored-*.json into the repo's data/ dir.
    Patches the settings instance directly (same pattern as set_tailor_token).
    """
    from app.settings import settings

    monkeypatch.setattr(settings, "cv_baseline_path", synthetic_baseline_path)
    monkeypatch.setattr(settings, "cv_tailored_dir", tmp_path / "tailored")
    yield
