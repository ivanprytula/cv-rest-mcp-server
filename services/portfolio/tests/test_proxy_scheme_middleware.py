from services.portfolio.proxy_scheme_middleware import TrustedProxySchemeMiddleware
from services.portfolio.settings import settings


async def _noop_receive():
    raise AssertionError("the middleware under test never calls receive()")


async def _noop_send(message):
    raise AssertionError("the middleware under test never calls send() directly")


async def _capture_scheme(
    scope: dict, headers: list[tuple[bytes, bytes]]
) -> str | None:
    seen: dict[str, str | None] = {"scheme": None}

    async def app(scope, receive, send):
        seen["scheme"] = scope.get("scheme")

    middleware = TrustedProxySchemeMiddleware(app)
    scope = {"type": "http", "headers": headers, **scope}
    await middleware(scope, _noop_receive, _noop_send)
    return seen["scheme"]


async def test_rewrites_scheme_when_trusted(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy", True)
    scheme = await _capture_scheme(
        {"scheme": "http"}, [(b"x-forwarded-proto", b"https")]
    )
    assert scheme == "https"


async def test_ignores_header_when_not_trusted(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy", False)
    scheme = await _capture_scheme(
        {"scheme": "http"}, [(b"x-forwarded-proto", b"https")]
    )
    assert scheme == "http"


async def test_no_header_leaves_scheme_untouched(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy", True)
    scheme = await _capture_scheme({"scheme": "http"}, [])
    assert scheme == "http"


async def test_rejects_unrecognized_scheme_value(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy", True)
    scheme = await _capture_scheme(
        {"scheme": "http"}, [(b"x-forwarded-proto", b"javascript:alert(1)")]
    )
    assert scheme == "http"


async def test_never_touches_client_scope(monkeypatch):
    # Deliberately does not rewrite scope["client"] -- that stays socket-peer
    # only so rate_limiter.peer_is_loopback's header-distrust boundary holds.
    monkeypatch.setattr(settings, "trust_proxy", True)
    seen: dict = {}

    async def app(scope, receive, send):
        seen["client"] = scope.get("client")

    middleware = TrustedProxySchemeMiddleware(app)
    scope = {
        "type": "http",
        "scheme": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [
            (b"x-forwarded-proto", b"https"),
            (b"x-forwarded-for", b"203.0.113.5"),
        ],
    }
    await middleware(scope, _noop_receive, _noop_send)
    assert seen["client"] == ("127.0.0.1", 12345)
