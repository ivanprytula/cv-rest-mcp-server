import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants import PDF_CACHE_MAX_ENTRIES, PDF_EXECUTOR_MAX_WORKERS
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
        {"category": "Testing", "items": ["pytest", "fixtures"]},
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
        synthetic_cv_path,
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


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
