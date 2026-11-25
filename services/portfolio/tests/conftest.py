import json
import os

import pytest
from httpx import ASGITransport, AsyncClient


collect_ignore = [
    "test_access_matrix.py",
    "test_analysis_worker.py",
    "test_ats.py",
    "test_ats_sync.py",
    "test_auth.py",
    "test_cv_extraction.py",
    "test_critic_agent.py",
    "test_matching/test_clustering.py",
    "test_documents_api.py",
    "test_events_publisher.py",
    "test_firestore_store.py",
    "test_gaps_api.py",
    "test_gen_secrets.py",
    "test_idempotency.py",
    "test_outbox.py",
    "test_pubsub_publisher.py",
    "test_review_service.py",
    "test_tenant_isolation.py",
    "test_tenancy_type.py",
    "test_tailor_jwt.py",
    "test_tracked_boards_api.py",
]

os.environ.update(
    {
        "FAILBAN_THRESHOLD": "0",
        "TRUST_PROXY": "false",
        "CLIENT_IP_XFF_ENTRY": "0",
        "CV_DATA_PATH": "data/cv.example.json",
        "CV_DATA_GCS_URI": "",
    }
)
os.environ.pop("ALLOWED_IPS_FILE", None)
os.environ.pop("BLOCKED_IPS_FILE", None)

from services.portfolio.constants import (  # noqa: E402
    PDF_CACHE_MAX_ENTRIES,
    PDF_EXECUTOR_MAX_WORKERS,
)
from services.portfolio.dependencies import get_pdf_service  # noqa: E402
from services.portfolio.documents.document_service import DocumentService  # noqa: E402
from services.portfolio.main import app  # noqa: E402
from services.portfolio.pdf_generator import PdfService  # noqa: E402
from services.portfolio.tenancy import TenantId  # noqa: E402


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


class FakeEmptyDocumentRepository:
    """Always misses, so `DocumentService` falls through to the file fallback.

    Enough for tests that just need a CV served — no Postgres, no rows.
    """

    async def get(self, kind, *, tenant_id):
        return None

    async def put(self, *, kind, payload, tenant_id):
        raise NotImplementedError

    async def list_all(self, *, tenant_id):
        return []

    async def delete(self, kind, *, tenant_id):
        return False


@pytest.fixture
def empty_document_repository():
    return FakeEmptyDocumentRepository()


@pytest.fixture
def fake_document_service(empty_document_repository):
    """`DocumentService` with no rows, so every read degrades to the file
    fallback — enough to back the public CV surface without real Postgres.
    """
    return DocumentService(empty_document_repository)


@pytest.fixture
def pdf_service(synthetic_cv_path, fake_document_service, monkeypatch):
    monkeypatch.setattr(
        "services.portfolio.pdf_generator.settings.cv_data_path", synthetic_cv_path
    )
    return PdfService(
        fake_document_service,
        TenantId(1),
        max_entries=PDF_CACHE_MAX_ENTRIES,
        max_workers=PDF_EXECUTOR_MAX_WORKERS,
    )


@pytest.fixture
def override_pdf_service(pdf_service, fake_document_service):
    """Wire the file-backed PDF service into the public CV surface."""
    from services.portfolio.dependencies import (
        get_document_service,
        get_operator_tenant_id,
    )

    app.dependency_overrides[get_pdf_service] = lambda: pdf_service
    app.state.pdf_service = pdf_service

    owns_document_service = getattr(app.state, "document_service", None) is None
    if owns_document_service:
        operator_tenant_id = TenantId(1)
        app.dependency_overrides[get_document_service] = lambda: fake_document_service
        app.dependency_overrides[get_operator_tenant_id] = lambda: operator_tenant_id
        app.state.document_service = fake_document_service
        app.state.operator_tenant_id = operator_tenant_id

    yield pdf_service

    app.dependency_overrides.pop(get_pdf_service, None)
    app.state.pdf_service = None
    if owns_document_service:
        app.dependency_overrides.pop(get_document_service, None)
        app.dependency_overrides.pop(get_operator_tenant_id, None)
        app.state.document_service = None
        app.state.operator_tenant_id = None


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


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


# Minimal vocabulary covering the same terms SYNTHETIC_BASELINE's skills use,
# so gap analysis (bank vs. vocabulary vs. posting text) has real matches to
# find rather than every term landing in "unknown" for lack of a vocabulary
# entry at all.
SYNTHETIC_VOCABULARY = {
    "_schema_version": "1",
    "terms": [
        {"term": "pytest", "group_id": "testing", "aliases": []},
        {"term": "Python", "group_id": "backend", "aliases": []},
        {"term": "FastAPI", "group_id": "backend", "aliases": []},
        {"term": "PostgreSQL", "group_id": "databases", "aliases": ["Postgres"]},
        {"term": "Redis", "group_id": "databases", "aliases": []},
        {"term": "Kubernetes", "group_id": "infra", "aliases": ["k8s"]},
        {"term": "Terraform", "group_id": "infra", "aliases": []},
        {"term": "GraphQL", "group_id": "backend", "aliases": []},
    ],
}


@pytest.fixture
def synthetic_vocabulary_path(tmp_path):
    path = tmp_path / "jd_vocabulary.json"
    path.write_text(json.dumps(SYNTHETIC_VOCABULARY, indent=2), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def tailor_settings(
    synthetic_baseline_path, synthetic_vocabulary_path, tmp_path, monkeypatch
):
    """Point the tailor/gap-analysis pipeline at synthetic data + a tmp revision dir.

    Autouse so every test is independent of the operator's real
    data/cv_baseline.json and data/jd_vocabulary.json (gitignored, real
    operator content, not part of this checkout) and no test ever writes a
    cv_tailored-*.json into the repo's data/ dir. Patches the settings
    instance directly.
    """
    from services.portfolio.settings import settings

    monkeypatch.setattr(settings, "cv_baseline_path", synthetic_baseline_path)
    monkeypatch.setattr(settings, "jd_vocabulary_path", synthetic_vocabulary_path)
    monkeypatch.setattr(settings, "cv_tailored_dir", tmp_path / "tailored")
    yield
