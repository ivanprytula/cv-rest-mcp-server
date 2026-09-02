from collections.abc import Callable

import pytest
from fastmcp.exceptions import ToolError
from starlette.requests import Request

from services.portfolio import mcp_limits


def _fake_http_request(ip: str, headers: dict[str, str] | None = None) -> Request:
    scope: dict = {
        "type": "http",
        "path": "/mcp/",
        "client": (ip, 12345),
        "headers": [
            (name.encode("latin-1"), value.encode("latin-1"))
            for name, value in (headers or {}).items()
        ],
    }
    return Request(scope)


def _patch_http_request(monkeypatch, factory: Callable[[], Request]) -> None:
    monkeypatch.setattr(mcp_limits, "get_http_request", factory)


def test_enforce_noop_without_http_context():
    # No FastMCP HTTP context in a plain test process: must not raise.
    mcp_limits.enforce_mcp_read_limit()
    mcp_limits.enforce_mcp_pdf_render_limit()


def test_read_limit_allows_burst_within_threshold(monkeypatch):
    _patch_http_request(monkeypatch, lambda: _fake_http_request("192.0.2.11"))
    for _ in range(30):
        mcp_limits.enforce_mcp_read_limit()


def test_read_limit_blocks_after_30_per_minute(monkeypatch):
    _patch_http_request(monkeypatch, lambda: _fake_http_request("192.0.2.12"))
    for _ in range(30):
        mcp_limits.enforce_mcp_read_limit()
    with pytest.raises(ToolError, match="Rate limit exceeded"):
        mcp_limits.enforce_mcp_read_limit()


def test_pdf_render_limit_blocks_after_5_per_15_minutes(monkeypatch):
    _patch_http_request(monkeypatch, lambda: _fake_http_request("192.0.2.13"))
    for _ in range(5):
        mcp_limits.enforce_mcp_pdf_render_limit()
    with pytest.raises(ToolError, match="Rate limit exceeded"):
        mcp_limits.enforce_mcp_pdf_render_limit()


def test_limits_are_isolated_per_client(monkeypatch):
    _patch_http_request(monkeypatch, lambda: _fake_http_request("192.0.2.14"))
    for _ in range(5):
        mcp_limits.enforce_mcp_pdf_render_limit()
    _patch_http_request(monkeypatch, lambda: _fake_http_request("192.0.2.15"))
    mcp_limits.enforce_mcp_pdf_render_limit()  # other client: untouched bucket


def test_limit_key_uses_xff_entry_when_configured(monkeypatch):
    from services.portfolio.settings import settings

    monkeypatch.setattr(settings, "client_ip_xff_entry", 2)
    monkeypatch.setattr(settings, "client_ip_header", "")
    # Both clients share the same real client IP at XFF position 2.
    _patch_http_request(
        monkeypatch,
        lambda: _fake_http_request(
            "10.0.0.1",
            headers={"x-forwarded-for": "198.51.100.9, 198.51.100.9, 10.0.0.1"},
        ),
    )
    for _ in range(5):
        mcp_limits.enforce_mcp_pdf_render_limit()
    with pytest.raises(ToolError, match="Rate limit exceeded"):
        mcp_limits.enforce_mcp_pdf_render_limit()


def test_pdf_render_stub_has_stacked_burst_and_hourly_limits():
    from services.portfolio.rate_limiter import limiter

    registered = limiter._route_limits[
        "services.portfolio.mcp_limits._limit_pdf_render"
    ]
    assert len(registered) == 2


def test_read_stub_has_stacked_burst_and_hourly_limits():
    from services.portfolio.rate_limiter import limiter

    registered = limiter._route_limits["services.portfolio.mcp_limits._limit_read"]
    assert len(registered) == 2


def test_enforce_skips_loopback_peers(monkeypatch):
    # Loopback socket peers are exempt service-wide: repeated calls never raise.
    _patch_http_request(monkeypatch, lambda: _fake_http_request("127.0.0.1"))
    for _ in range(10):
        mcp_limits.enforce_mcp_pdf_render_limit()
        mcp_limits.enforce_mcp_read_limit()
