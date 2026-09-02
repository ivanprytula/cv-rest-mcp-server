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
    }
)
os.environ.pop("ALLOWED_IPS_FILE", None)
os.environ.pop("BLOCKED_IPS_FILE", None)

from services.portfolio.constants import PDF_CACHE_MAX_ENTRIES, PDF_EXECUTOR_MAX_WORKERS
from services.portfolio.cv_source import CvSource
from services.portfolio.dependencies import get_pdf_service
from services.portfolio.main import app
from services.portfolio.pdf_generator import PdfService


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


@pytest.fixture
def admin_access_token(auth_settings):
    """A valid admin (cv:manage + cv:read) access JWT for the protected surface.

    Depends on `auth_settings` so the signing key + issuer/audience are
    configured before minting. Used both to seed the `client` fixture's default
    Authorization header and directly by tests that must place a typed/scoped
    token into a `?token=` query param.
    """
    from services.portfolio.auth.crypto import sign_access_token

    return sign_access_token("operator", ["cv:read", "cv:manage"], role="admin")


@pytest.fixture
async def client(admin_access_token):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {admin_access_token}"},
    ) as ac:
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


@pytest.fixture(autouse=True)
def tailor_settings(synthetic_baseline_path, tmp_path, monkeypatch):
    """Point the tailor pipeline at the synthetic bank + a tmp revision dir.

    Autouse so every test is independent of the operator's data/cv_baseline.json
    and     no test ever writes a cv_tailored-*.json into the repo's data/ dir.
    Patches the settings instance directly (same pattern as the auth fixtures).
    """
    from services.portfolio.settings import settings

    monkeypatch.setattr(settings, "cv_baseline_path", synthetic_baseline_path)
    monkeypatch.setattr(settings, "cv_tailored_dir", tmp_path / "tailored")
    yield


# --- Phase 1c auth fixtures -------------------------------------------------


@pytest.fixture
def auth_settings(synthetic_baseline_path, tmp_path, monkeypatch):
    """Configure the auth module for a test: signing key + JWT knobs.

    Sets an ephemeral HS256 signing secret (a plain string — symmetric JWT), a
    refresh pepper, and a pinned CORS origin, then clears the in-memory token
    store so families don't leak across tests. Patches the settings instance
    directly (same pattern as the other settings fixtures). Returns a dict with the
    configured secrets (`jwt_signing_key`, `pepper`).

    User passwords are NOT configured here — they live in the SQLAlchemy-backed
    user store (see the `user_service` fixture below), per ADR-022 Phase 2.
    """
    from services.portfolio.auth.token_store import token_store
    from services.portfolio.settings import settings

    signing_key = "test-hs256-secret-that-is-long-enough-for-signing"

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "jwt_signing_key", signing_key)
    monkeypatch.setattr(settings, "refresh_token_pepper", "test-pepper")
    monkeypatch.setattr(settings, "jwt_audience", "cv-rest-mcp-server")
    monkeypatch.setattr(settings, "jwt_issuer", "https://api.example.com")
    monkeypatch.setattr(settings, "cors_origin", "https://app.example.com")
    monkeypatch.setattr(settings, "access_token_ttl_minutes", 10)
    monkeypatch.setattr(settings, "refresh_token_ttl_days", 30)

    token_store.clear()
    yield {"jwt_signing_key": signing_key, "pepper": "test-pepper"}


@pytest.fixture
async def user_service(auth_settings, tmp_path, monkeypatch):
    """A per-test SQLAlchemy-backed user service on an isolated temp DB.

    Builds a fresh repo/service, creates the schema, seeds the first admin
    (username=`operator`, password=`correct-password`, role=`admin`), and swaps
    it into `app.auth.user_store.user_service` so the auth routes (which look it
    up dynamically) hit this isolated store. Matches the `login()` helper's
    defaults used across the auth tests.
    """
    from services.portfolio.auth import user_store as user_store_module
    from services.portfolio.auth.user_store import (
        Base,
        UserRepository,
        UserService,
        sqlite_url_for,
    )
    from services.portfolio.settings import settings

    db_path = tmp_path / "auth_test.db"
    repo = UserRepository(sqlite_url_for(db_path))
    service = UserService(repo)

    # Initialize schema (moved from service to lifecycle in main.py).
    async with repo.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await service.seed_first_admin(
        username="operator",
        email="operator@example.com",
        password="correct-password",
        role="admin",
    )

    monkeypatch.setattr(settings, "user_db_path", db_path)
    monkeypatch.setattr(user_store_module, "user_service", service)
    yield service
    await repo.engine.dispose()


@pytest.fixture
async def auth_client(user_service, override_pdf_service):
    """httpx client for auth endpoints with auth + PDF service configured.

    `override_pdf_service` sets `app.state.pdf_service` so public CV routes
    (which the middleware-passthrough tests hit) can render.
    """
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
