"""CV extraction: the tool-use parsing branch, and the route's failure modes.

No real Anthropic call is made — the client is stubbed at the
`messages.create` boundary, since exercising the actual API is neither
deterministic nor free.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import pytest
from fastapi import status

from services.portfolio.cv_extraction import (
    CVExtractionError,
    CVExtractionService,
    _tool_schema,
)


def _tool_use_response(input_data: dict):
    block = SimpleNamespace(type="tool_use", name="record_cv", input=input_data)
    return SimpleNamespace(content=[block])


def test_tool_schema_forbids_extra_top_level_keys():
    # Regression: CVData.model_config allows extra fields for stored
    # documents, but the model once used that to wrap its whole answer in
    # an invented "cv" key, leaving every real field empty.
    assert _tool_schema()["input_schema"]["additionalProperties"] is False


class TestExtract:
    async def test_returns_validated_cv_payload_from_the_tool_call(self):
        client = SimpleNamespace(
            messages=SimpleNamespace(
                create=AsyncMock(
                    return_value=_tool_use_response({"name": "Ada Lovelace"})
                )
            )
        )
        service = CVExtractionService(client)

        draft = await service.extract("Ada Lovelace, mathematician...")

        assert draft["name"] == "Ada Lovelace"

    async def test_raises_when_the_model_returns_no_tool_call(self):
        client = SimpleNamespace(
            messages=SimpleNamespace(
                create=AsyncMock(return_value=SimpleNamespace(content=[]))
            )
        )
        service = CVExtractionService(client)

        with pytest.raises(CVExtractionError, match="did not return"):
            await service.extract("some resume text")

    async def test_raises_when_the_extraction_fails_schema_validation(self):
        client = SimpleNamespace(
            messages=SimpleNamespace(
                create=AsyncMock(
                    return_value=_tool_use_response({"education": "not-a-list"})
                )
            )
        )
        service = CVExtractionService(client)

        with pytest.raises(CVExtractionError, match="validation"):
            await service.extract("some resume text")

    async def test_wraps_an_api_error(self):
        async def _raise(*args, **kwargs):
            raise anthropic.APIConnectionError(request=AsyncMock())

        client = SimpleNamespace(messages=SimpleNamespace(create=_raise))
        service = CVExtractionService(client)

        with pytest.raises(CVExtractionError, match="extraction call failed"):
            await service.extract("some resume text")


DOCS = "/api/v1/documents"


@pytest.fixture
async def admin_client(auth_client):
    password = "correct-password"  # pragma: allowlist secret
    resp = await auth_client.post(
        "/api/v1/auth/token", json={"username": "operator", "password": password}
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    auth_client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return auth_client


@pytest.fixture
def stub_extraction_service():
    """Installs a fake `cv_extraction_service`, torn down after the test.

    The real one is only ever wired when ANTHROPIC_API_KEY is set (never
    true in tests), so route behavior that only kicks in once a service
    exists needs a stand-in installed directly on `app.state`.
    """
    from services.portfolio.main import app

    installed: dict = {}

    def _install(service):
        app.state.cv_extraction_service = service
        installed["set"] = True

    yield _install
    if installed:
        app.state.cv_extraction_service = None


class TestExtractRoute:
    async def test_unconfigured_extraction_is_503(self, admin_client):
        # No ANTHROPIC_API_KEY in test settings, so main.py's lifespan never
        # sets app.state.cv_extraction_service.
        resp = await admin_client.post(
            f"{DOCS}/cv/extract",
            content=b"Ada Lovelace, mathematician",
            headers={"content-type": "text/plain"},
        )
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    async def test_requires_authentication(self, client):
        resp = await client.post(
            f"{DOCS}/cv/extract",
            content=b"resume text",
            headers={"content-type": "text/plain", "Authorization": ""},
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_oversized_extracted_text_is_413(
        self, admin_client, stub_extraction_service
    ):
        from services.portfolio.cv_extraction import MAX_RESUME_TEXT_CHARS

        class _UnusedService:
            async def extract(self, resume_text):
                raise AssertionError("extract() must not run past the size check")

        stub_extraction_service(_UnusedService())
        oversized = b"a" * (MAX_RESUME_TEXT_CHARS + 1)
        resp = await admin_client.post(
            f"{DOCS}/cv/extract",
            content=oversized,
            headers={"content-type": "text/plain"},
        )
        assert resp.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

    async def test_extraction_failure_does_not_leak_the_raw_exception(
        self, admin_client, stub_extraction_service
    ):
        class _FailingService:
            async def extract(self, resume_text):
                raise CVExtractionError(
                    "upstream detail: internal-request-id=abc123 secret=xyz"
                )

        stub_extraction_service(_FailingService())
        resp = await admin_client.post(
            f"{DOCS}/cv/extract",
            content=b"some resume text",
            headers={"content-type": "text/plain"},
        )

        assert resp.status_code == status.HTTP_502_BAD_GATEWAY
        assert "secret=xyz" not in resp.text
        assert "internal-request-id" not in resp.text
