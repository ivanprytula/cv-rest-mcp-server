"""`analysis_worker`'s Pub/Sub push route.

Fakes `GapService`/`DocumentService` on `app.state` directly rather than
running the app's lifespan (no real DB needed) — the same "assert the call
sequence" style as `test_ats_sync.py`'s spy-publisher test, since what's
under test here is envelope decoding and orchestration, not persistence.
"""

import base64
import json

import httpx
import pytest

from services.portfolio.analysis_worker import app
from services.portfolio.matching.baseline import BaselineError
from services.portfolio.tenancy import TenantId


def _push_envelope(payload: dict) -> dict:
    data = base64.b64encode(json.dumps(payload).encode()).decode()
    return {"message": {"data": data, "messageId": "1"}, "subscription": "test-sub"}


class _FakeGapService:
    def __init__(self):
        self.analyze_calls: list[dict] = []
        self.cluster_calls: list[dict] = []

    async def analyze_posting(self, posting_id, **kwargs):
        self.analyze_calls.append({"posting_id": posting_id, **kwargs})

    async def cluster_posting(self, posting_id, *, tenant_id):
        self.cluster_calls.append({"posting_id": posting_id, "tenant_id": tenant_id})


class _FakeDocumentService:
    async def read(self, kind, *, tenant_id, fallback_path=None):
        return {}


@pytest.fixture
async def client(monkeypatch):
    fake_gap_service = _FakeGapService()
    app.state.gap_service = fake_gap_service
    app.state.document_service = _FakeDocumentService()

    async def fake_load_analysis_inputs(documents, *, tenant_id):
        return ([], [], [], {})

    monkeypatch.setattr(
        "services.portfolio.analysis_worker.load_analysis_inputs",
        fake_load_analysis_inputs,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as async_client:
        yield async_client, fake_gap_service


async def test_processes_a_posting_changed_event(client):
    async_client, fake_gap_service = client
    response = await async_client.post(
        "/pubsub/posting-changed",
        json=_push_envelope(
            {
                "posting_id": 42,
                "tenant_id": 1,
                "status": "new",
                "content_hash": "abc",
            }
        ),
    )
    assert response.status_code == 200
    assert response.json() == {"status": "processed"}
    assert fake_gap_service.analyze_calls == [
        {
            "posting_id": 42,
            "tenant_id": TenantId(1),
            "bank_atoms": [],
            "deferred_atoms": [],
            "vocabulary": [],
            "live_cv": {},
            "aliases": {},
        }
    ]
    assert fake_gap_service.cluster_calls == [
        {"posting_id": 42, "tenant_id": TenantId(1)}
    ]


async def test_malformed_envelope_returns_400(client):
    async_client, _ = client
    response = await async_client.post(
        "/pubsub/posting-changed", json={"not": "a push envelope"}
    )
    assert response.status_code == 400


async def test_missing_baseline_skips_without_error(client, monkeypatch):
    async_client, fake_gap_service = client

    async def fake_load_analysis_inputs(documents, *, tenant_id):
        raise BaselineError("no skill bank configured")

    monkeypatch.setattr(
        "services.portfolio.analysis_worker.load_analysis_inputs",
        fake_load_analysis_inputs,
    )

    response = await async_client.post(
        "/pubsub/posting-changed",
        json=_push_envelope(
            {"posting_id": 7, "tenant_id": 1, "status": "changed", "content_hash": "x"}
        ),
    )
    assert response.status_code == 200
    assert response.json() == {"status": "skipped"}
    assert fake_gap_service.analyze_calls == []
