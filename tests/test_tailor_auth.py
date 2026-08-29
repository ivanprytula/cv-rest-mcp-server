"""Tests for TailorAuthMiddleware (bearer-token gate on POST /cv/tailor).

The middleware is path-scoped: it must NOT affect any other route. Every
test that exercises /cv/tailor asserts either the deny path (401/503)
or a positive path. Every test that touches a different route asserts
the middleware is a no-op there.

The middleware is pure ASGI, so we exercise it both ways:
- Direct ASGI scope calls (matches the pattern in test_guards.py).
- End-to-end through the FastAPI app via AsyncClient (proves the
  middleware is actually wired into main.py).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.types import Receive, Scope, Send

from app.main import app
from app.settings import settings
from app.tailor_auth import (
    TailorAuthMiddleware,
    _extract_bearer,
    _is_configured,
    _query_param,
    _resolve_token,
)


# --- helpers ---------------------------------------------------------------


class _CaptureApp:
    """ASGI app that records whether it was invoked.

    Used to assert the middleware's pass-through behaviour. If `called` is
    True after a scope dispatch, the downstream app was reached.
    """

    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.called = True


def _make_scope(
    method: str = "POST",
    path: str = "/cv/tailor",
    headers: list[tuple[bytes, bytes]] | None = None,
    query_string: bytes = b"",
) -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "query_string": query_string,
    }


def _make_receive_send() -> tuple[Any, Any, list[dict[str, Any]]]:
    """Build a real receive/send pair and a sink for the captured messages.

    Mirrors the `_run_guard` pattern in tests/test_guards.py: the middleware
    needs actual callables (not None) because Starlette's ASGI signature is
    strict and `ty` enforces it. Returns (receive, send, captured).
    """
    captured: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request"}

    async def send(message: dict[str, Any]) -> None:
        captured.append(message)

    return receive, send, captured


async def _send_to(send, status: int, body: bytes) -> None:
    await send({"type": "http.response.start", "status": status, "headers": []})
    await send({"type": "http.response.body", "body": body})


# --- header parsing unit tests --------------------------------------------


def test_extract_bearer_returns_malformed_when_header_missing():
    token, malformed = _extract_bearer([])
    assert token is None
    assert malformed is True


def test_extract_bearer_returns_malformed_when_scheme_wrong():
    token, malformed = _extract_bearer([(b"authorization", b"Basic abc123")])
    assert token is None
    assert malformed is True


def test_extract_bearer_accepts_lowercase_scheme():
    token, malformed = _extract_bearer([(b"authorization", b"bearer secret-token")])
    assert token == "secret-token"
    assert malformed is False


def test_extract_bearer_treats_empty_token_as_no_token():
    token, malformed = _extract_bearer([(b"authorization", b"Bearer ")])
    # Well-formed scheme but no token — the middleware rejects with 401
    # in its `if malformed or token is None` branch.
    assert token is None
    assert malformed is False


def test_extract_bearer_strips_surrounding_whitespace():
    token, malformed = _extract_bearer([(b"authorization", b"Bearer   abc   ")])
    assert token == "abc"
    assert malformed is False


# --- configuration helpers -------------------------------------------------


def test_is_configured_false_when_empty(monkeypatch):
    monkeypatch.setattr(settings, "tailor_bearer_token", "")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    assert _is_configured() is False


def test_is_configured_true_with_inline_value(monkeypatch):
    monkeypatch.setattr(settings, "tailor_bearer_token", "x")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    assert _is_configured() is True


def test_resolve_token_prefers_file_over_inline(monkeypatch, tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("from-file\n", encoding="utf-8")
    monkeypatch.setattr(settings, "tailor_bearer_token", "from-inline")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", token_file)
    assert _resolve_token() == "from-file"


def test_resolve_token_raises_when_configured_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "tailor_bearer_token", "")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", tmp_path / "nope")
    with pytest.raises(FileNotFoundError):
        _resolve_token()


# --- direct ASGI dispatch --------------------------------------------------


def _send_capturing() -> tuple[Any, Any, dict[str, Any]]:
    """Return (receive, send, captured) where captured collects start/body.

    `captured["status"]`, `captured["body"]`, and `captured["headers"]` are
    populated as the middleware emits them. Mirrors the `_run_guard` pattern
    in tests/test_guards.py.
    """
    captured: dict[str, Any] = {}

    async def receive() -> dict[str, Any]:
        return {"type": "http.request"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
            captured["headers"] = message.get("headers", [])
        elif message["type"] == "http.response.body":
            captured["body"] = message["body"]

    return receive, send, captured


async def test_pass_through_when_scope_not_http():
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, _captured = _send_capturing()
    await mw({"type": "lifespan"}, receive, send)
    assert app_called.called is True


async def test_pass_through_when_method_is_not_post(monkeypatch):
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, _captured = _send_capturing()
    await mw(_make_scope(method="GET", path="/cv/tailor"), receive, send)
    assert app_called.called is True


async def test_pass_through_when_path_is_not_tailor(monkeypatch):
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, _captured = _send_capturing()
    await mw(_make_scope(method="POST", path="/cv"), receive, send)
    assert app_called.called is True


async def test_503_when_no_token_configured(monkeypatch):
    monkeypatch.setattr(settings, "tailor_bearer_token", "")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, captured = _send_capturing()
    await mw(_make_scope(), receive, send)
    assert app_called.called is False
    assert captured["status"] == 503
    assert b"TAILOR_BEARER_TOKEN" in captured["body"]


async def test_503_when_token_resolves_to_empty(monkeypatch):
    monkeypatch.setattr(settings, "tailor_bearer_token", "   ")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, captured = _send_capturing()
    await mw(_make_scope(), receive, send)
    assert app_called.called is False
    assert captured["status"] == 503


async def test_503_when_configured_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "tailor_bearer_token", "")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", tmp_path / "nope")
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, captured = _send_capturing()
    await mw(_make_scope(), receive, send)
    assert app_called.called is False
    assert captured["status"] == 503


async def test_401_when_authorization_header_missing(monkeypatch):
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, captured = _send_capturing()
    await mw(_make_scope(), receive, send)
    assert app_called.called is False
    assert captured["status"] == 401
    assert b"Missing or malformed" in captured["body"]
    # WWW-Authenticate header must be present so clients know the scheme
    headers_lower = {k.lower(): v for k, v in captured["headers"]}
    assert headers_lower.get(b"www-authenticate") == b"Bearer"


async def test_401_when_authorization_malformed(monkeypatch):
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, captured = _send_capturing()
    await mw(_make_scope(headers=[(b"authorization", b"Basic xyz")]), receive, send)
    assert app_called.called is False
    assert captured["status"] == 401
    assert b"Missing or malformed" in captured["body"]


async def test_401_when_token_mismatched(monkeypatch):
    monkeypatch.setattr(settings, "tailor_bearer_token", "correct-horse-battery-staple")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, captured = _send_capturing()
    headers = [(b"authorization", b"Bearer wrong-token")]
    await mw(_make_scope(headers=headers), receive, send)
    assert app_called.called is False
    assert captured["status"] == 401
    assert b"Invalid bearer token" in captured["body"]


async def test_pass_through_when_token_matches(monkeypatch):
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret-token")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, _captured = _send_capturing()
    headers = [(b"authorization", b"Bearer secret-token")]
    await mw(_make_scope(headers=headers), receive, send)
    assert app_called.called is True


async def test_never_logs_the_token(monkeypatch, caplog):
    """The Authorization header must not appear in any log line.

    Guards against future regressions where someone "helpfully" logs the
    bad token for debugging. The OWASP rule is: never log credentials.
    """
    import logging

    monkeypatch.setattr(settings, "tailor_bearer_token", "do-not-leak")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, _captured = _send_capturing()
    headers = [(b"authorization", b"Bearer do-not-leak")]
    with caplog.at_level(logging.WARNING):
        await mw(_make_scope(headers=headers), receive, send)
    assert "do-not-leak" not in caplog.text


# --- tailored-revision read gating (unit) ----------------------------------


def test_query_param_returns_stripped_first_value():
    assert (
        _query_param(
            {"query_string": b"theme=classic&tailored=latest&tailored=old"},
            "tailored",
        )
        == "latest"
    )
    assert _query_param({"query_string": b"tailored="}, "tailored") == ""
    assert _query_param({"query_string": b""}, "token") == ""


async def test_pass_through_on_tailored_read_without_tailored_param(monkeypatch):
    """GET /cv/html without a `tailored` selector stays public (no auth)."""
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, _captured = _send_capturing()
    await mw(
        _make_scope(method="GET", path="/cv/html", query_string=b"theme=classic"),
        receive,
        send,
    )
    assert app_called.called is True


async def test_pass_through_on_tailored_read_with_empty_tailored_param(monkeypatch):
    """`?tailored=` with an empty value is not a revision view (no auth)."""
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, _captured = _send_capturing()
    await mw(
        _make_scope(method="GET", path="/cv/html", query_string=b"tailored="),
        receive,
        send,
    )
    assert app_called.called is True


async def test_401_on_tailored_read_without_credentials(monkeypatch):
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, captured = _send_capturing()
    await mw(
        _make_scope(method="GET", path="/cv/html", query_string=b"tailored=latest"),
        receive,
        send,
    )
    assert app_called.called is False
    assert captured["status"] == 401


async def test_401_on_tailored_read_with_wrong_query_token(monkeypatch):
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, captured = _send_capturing()
    await mw(
        _make_scope(
            method="GET",
            path="/cv/preview",
            query_string=b"tailored=latest&token=wrong",
        ),
        receive,
        send,
    )
    assert app_called.called is False
    assert captured["status"] == 401
    assert b"Invalid bearer token" in captured["body"]


async def test_pass_through_on_tailored_read_with_query_token(monkeypatch):
    """A GET revision read accepts `?token=` when no header is present."""
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, _captured = _send_capturing()
    await mw(
        _make_scope(
            method="GET",
            path="/cv/pdf",
            query_string=b"tailored=cv_tailored-x.json&token=secret",
        ),
        receive,
        send,
    )
    assert app_called.called is True


async def test_header_takes_precedence_over_query_token(monkeypatch):
    """A present-but-wrong header must win over a valid `?token=`."""
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, captured = _send_capturing()
    await mw(
        _make_scope(
            method="GET",
            path="/cv/html",
            headers=[(b"authorization", b"Bearer wrong")],
            query_string=b"tailored=latest&token=secret",
        ),
        receive,
        send,
    )
    assert app_called.called is False
    assert captured["status"] == 401


async def test_mutation_route_ignores_query_token(monkeypatch):
    """POST /cv/tailor never accepts a token in the query string."""
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, captured = _send_capturing()
    await mw(
        _make_scope(query_string=b"token=secret"),
        receive,
        send,
    )
    assert app_called.called is False
    assert captured["status"] == 401


async def test_503_fail_closed_applies_to_tailored_read(monkeypatch):
    monkeypatch.setattr(settings, "tailor_bearer_token", "")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)
    app_called = _CaptureApp()
    mw = TailorAuthMiddleware(app_called)
    receive, send, captured = _send_capturing()
    await mw(
        _make_scope(method="GET", path="/cv/html", query_string=b"tailored=latest"),
        receive,
        send,
    )
    assert app_called.called is False
    assert captured["status"] == 503


# --- end-to-end via FastAPI app -------------------------------------------


async def test_e2e_503_when_token_not_configured(
    monkeypatch, client, override_pdf_service
):
    """When the operator forgets to set TAILOR_BEARER_TOKEN, /cv/tailor
    must be unreachable, but the rest of the public surface must work.
    """
    monkeypatch.setattr(settings, "tailor_bearer_token", "")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)

    # /cv/tailor is denied
    resp = await client.post("/cv/tailor", content="some JD text")
    assert resp.status_code == 503
    assert "TAILOR_BEARER_TOKEN" in resp.text

    # Public surface still works
    resp = await client.get("/health")
    assert resp.status_code == 200
    resp = await client.get("/cv")
    assert resp.status_code == 200


async def test_e2e_401_when_token_missing(monkeypatch):
    """No Authorization header → 401. The `client` fixture injects a
    default Authorization header, so we build a fresh client with no
    default headers for this test.
    """
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/cv/tailor", content="some JD text")
        assert resp.status_code == 401
        assert resp.headers.get("www-authenticate") == "Bearer"
        assert "Missing or malformed" in resp.text


async def test_e2e_401_when_token_wrong(monkeypatch):
    """Wrong token → 401. The default Authorization header in the
    `client` fixture uses TAILOR_TEST_TOKEN, so we override with `wrong`.
    """
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/cv/tailor",
            content="some JD text",
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401
        assert "Invalid bearer token" in resp.text


async def test_e2e_unrelated_routes_unaffected(monkeypatch, override_pdf_service):
    """The middleware must NOT touch any route other than POST /cv/tailor.

    This is the scope regression test. Even with a token configured, GET
    /cv and GET /health must continue to work without an Authorization
    header. /mcp is a separate sub-app mount; this test only covers REST
    routes registered on the main FastAPI app.
    """
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # GET routes pass without auth
        assert (await ac.get("/health")).status_code == 200
        assert (await ac.get("/cv")).status_code == 200
        assert (await ac.get("/cv/html")).status_code == 200
        assert (await ac.get("/cv/pdf")).status_code == 200
        # POST to a different path is unaffected (will hit routing normally)
        # /cv/tailor with the correct token reaches the route handler
        resp = await ac.post(
            "/cv/tailor",
            content="x",  # tiny body — route will 422, not 401
            headers={"Authorization": "Bearer secret"},
        )
        # The route's own validation kicks in (422) — auth passed
        assert resp.status_code in (200, 422)
        assert resp.status_code != 401
        assert resp.status_code != 503


async def test_e2e_tailored_read_fail_closed(monkeypatch):
    """No token configured → the `?tailored=` view is 503, like /cv/tailor."""
    monkeypatch.setattr(settings, "tailor_bearer_token", "")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/cv/html?tailored=latest")
        assert resp.status_code == 503
        assert "TAILOR_BEARER_TOKEN" in resp.text


async def test_e2e_tailored_read_401_without_credentials(monkeypatch):
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/cv/pdf?tailored=latest")
        assert resp.status_code == 401
        assert resp.headers.get("www-authenticate") == "Bearer"


async def test_e2e_tailored_read_query_token_reaches_route(
    monkeypatch, override_pdf_service
):
    """`?token=` on a read is accepted; the route then decides (404 here)."""
    monkeypatch.setattr(settings, "tailor_bearer_token", "secret")
    monkeypatch.setattr(settings, "tailor_bearer_token_file", None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/cv/html?tailored=nope.json&token=secret")
        assert resp.status_code == 404
        assert "not found" in resp.text
