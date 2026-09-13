"""Correlation-id middleware and the log filter that surfaces it.

Asserts against real log records rather than the ContextVar directly: the
whole point of the id is that it reaches log output, and a test that only
checks the variable would pass even if the filter were never wired to the
handler.
"""

import logging

import httpx
import pytest
from fastapi import FastAPI

from shared.logging_config import TraceIdFilter
from shared.tracing import (
    TraceContextMiddleware,
    bind_trace_id,
    current_trace_id,
)


@pytest.fixture
def app() -> FastAPI:
    """A minimal app that logs once per request, behind the middleware."""
    application = FastAPI()
    application.add_middleware(TraceContextMiddleware)

    @application.get("/ping")
    async def ping() -> dict[str, str]:
        logging.getLogger("test.tracing").info("handled")
        return {"trace_id": current_trace_id()}

    return application


@pytest.fixture
async def client(app: FastAPI):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as async_client:
        yield async_client


async def test_header_trace_id_reaches_log_records(client, caplog):
    caplog.set_level(logging.INFO)
    caplog.handler.addFilter(TraceIdFilter())

    response = await client.get(
        "/ping", headers={"X-Cloud-Trace-Context": "abc123def456/9876543210;o=1"}
    )

    assert response.status_code == 200
    # Only the id, not the span suffix or the sampling flag.
    assert response.json()["trace_id"] == "abc123def456"
    record = next(r for r in caplog.records if r.message == "handled")
    assert record.trace_id == "abc123def456"


async def test_request_without_header_still_gets_an_id(client):
    """Off Cloud Run there is no header, and correlation must not silently
    degrade to no id at all."""
    response = await client.get("/ping")

    assert response.json()["trace_id"] != ""


async def test_ids_do_not_leak_between_requests(client):
    """The ContextVar is reset in a finally: the same task serves later
    requests, and a stale id is worse than none."""
    first = await client.get(
        "/ping", headers={"X-Cloud-Trace-Context": "first-trace/1;o=1"}
    )
    second = await client.get(
        "/ping", headers={"X-Cloud-Trace-Context": "second-trace/1;o=1"}
    )

    assert first.json()["trace_id"] == "first-trace"
    assert second.json()["trace_id"] == "second-trace"
    # And nothing is left bound once the requests are over.
    assert current_trace_id() == ""


async def test_no_trace_id_field_outside_a_request(caplog):
    """The filter adds nothing when no id is bound, so background/CLI log
    lines keep their existing shape."""
    caplog.set_level(logging.INFO)
    caplog.handler.addFilter(TraceIdFilter())

    logging.getLogger("test.tracing").info("standalone")

    record = next(r for r in caplog.records if r.message == "standalone")
    assert not hasattr(record, "trace_id")


def test_bind_trace_id_adopts_and_restores():
    """How the relay and the worker continue a trace that began elsewhere."""
    assert current_trace_id() == ""

    with bind_trace_id("carried-id") as bound:
        assert bound == "carried-id"
        assert current_trace_id() == "carried-id"

    assert current_trace_id() == ""


def test_bind_trace_id_generates_one_when_empty():
    """A falsy id means "no originator recorded" — the work still needs to be
    attributable to something."""
    with bind_trace_id(None) as bound:
        assert bound
        assert current_trace_id() == bound


def test_gcp_trace_field_is_added_only_with_a_project(monkeypatch):
    """`logging.googleapis.com/trace` is what makes Cloud Logging join the
    line to the platform's trace; it needs a project id, which is unset
    locally and in tests."""
    record = logging.LogRecord("t", logging.INFO, "", 0, "msg", (), None)
    log_filter = TraceIdFilter()

    with bind_trace_id("abc123"):
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        log_filter.filter(record)
        assert not hasattr(record, "logging.googleapis.com/trace")

        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
        log_filter.filter(record)
        assert (
            getattr(record, "logging.googleapis.com/trace")
            == "projects/demo-project/traces/abc123"
        )
