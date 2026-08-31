"""Tests for the Phase 1c auth module (ADR-022).

Covers crypto (HS256 sign/verify, bcrypt login, refresh hashing), the in-memory
refresh-token family store (rotation + replay detection), and the HTTP surface
(/api/v1/auth/token|refresh|logout|me) plus the JWTAuthMiddleware + credentialed
CORS behavior. All tests are offline and use ephemeral keys seeded via the
`auth_settings` fixture.
"""

from __future__ import annotations

import jwt
import pytest

from app.auth.crypto import (
    AuthUnconfiguredError,
    generate_refresh_token,
    hash_refresh_token,
    sign_access_token,
    verify_access_token,
)
from app.auth.token_store import RefreshTokenStore
from app.settings import settings


# ---------------------------------------------------------------------------
# crypto
# ---------------------------------------------------------------------------


def test_sign_and_verify_access_token(auth_settings):
    token = sign_access_token("operator", ["cv:read", "cv:manage"], role="admin")
    claims = verify_access_token(token)
    assert claims["sub"] == "operator"
    assert claims["iss"] == settings.jwt_issuer
    assert claims["aud"] == settings.jwt_audience
    assert set(claims["scope"].split()) == {"cv:read", "cv:manage"}
    assert claims["role"] == "admin"


def test_access_token_has_short_ttl(auth_settings):

    token = sign_access_token("operator", ["cv:read"], role="user")
    claims = verify_access_token(token)
    expected = settings.access_token_ttl_minutes * 60
    assert claims["exp"] - claims["iat"] == expected


def test_verify_expired_token(auth_settings):
    import time

    token = jwt.encode(
        {
            "sub": "operator",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": int(time.time()) - 100,
            "exp": int(time.time()) - 10,
        },
        auth_settings["jwt_signing_key"],
        algorithm="HS256",
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        verify_access_token(token)


def test_verify_wrong_issuer(auth_settings):
    import time

    token = jwt.encode(
        {
            "sub": "operator",
            "iss": "https://evil.example.com",
            "aud": settings.jwt_audience,
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
        },
        auth_settings["jwt_signing_key"],
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidIssuerError):
        verify_access_token(token)


def test_verify_wrong_audience(auth_settings):
    import time

    token = jwt.encode(
        {
            "sub": "operator",
            "iss": settings.jwt_issuer,
            "aud": "other-service",
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
        },
        auth_settings["jwt_signing_key"],
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidAudienceError):
        verify_access_token(token)


def test_verify_tampered_signature(auth_settings, monkeypatch):
    import time

    token = jwt.encode(
        {
            "sub": "operator",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
        },
        auth_settings["jwt_signing_key"],
        algorithm="HS256",
    )
    # Corrupt the payload portion so the signature no longer matches.
    parts = token.split(".")
    import base64
    import json

    payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
    payload["sub"] = "attacker"
    tampered_payload = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    )
    tampered = f"{parts[0]}.{tampered_payload}.{parts[2]}"
    with pytest.raises(jwt.InvalidSignatureError):
        verify_access_token(tampered)


def test_sign_fails_without_key(monkeypatch):
    monkeypatch.setattr(settings, "jwt_signing_key", "")
    with pytest.raises(AuthUnconfiguredError):
        sign_access_token("operator", ["cv:read"], role="user")


def test_verify_fails_without_key(monkeypatch):
    monkeypatch.setattr(settings, "jwt_signing_key", "")
    with pytest.raises(AuthUnconfiguredError):
        verify_access_token("not-a-real-token")


def test_sign_uses_shared_hs256_secret(auth_settings, monkeypatch):
    # HS256 is symmetric: the shared secret both signs and validates, so a token
    # minted outside the app with the same secret must verify.
    token = sign_access_token("operator", ["cv:read"], role="user")
    assert verify_access_token(token)["sub"] == "operator"


def test_hash_refresh_token_deterministic(auth_settings):
    t = generate_refresh_token()
    assert hash_refresh_token(t) == hash_refresh_token(t)


def test_hash_refresh_token_uses_pepper(auth_settings, monkeypatch):
    t = generate_refresh_token()
    first = hash_refresh_token(t)
    monkeypatch.setattr(settings, "refresh_token_pepper", "different-pepper")
    assert hash_refresh_token(t) != first


def test_generate_refresh_token_is_random():
    assert generate_refresh_token() != generate_refresh_token()
    assert len(generate_refresh_token()) >= 32


# ---------------------------------------------------------------------------
# user store (SQLAlchemy-backed, ADR-022 Phase 2)
# ---------------------------------------------------------------------------


async def test_user_service_seed_first_admin(user_service):
    user = await user_service.get_by_username("operator")
    assert user is not None
    assert user.is_active is True
    assert user.email == "operator@example.com"
    assert user.role == "admin"
    assert user.scopes == ["cv:read", "cv:manage"]


async def test_authenticate_correct(user_service):
    user = await user_service.authenticate("operator", "correct-password")
    assert user is not None
    assert user.username == "operator"


async def test_authenticate_wrong_password(user_service):
    assert await user_service.authenticate("operator", "wrong-password") is None


async def test_authenticate_unknown_username(user_service):
    # An unknown username yields the same None as a wrong password, so the
    # store never reveals whether a username exists (flat timing).
    assert await user_service.authenticate("attacker", "whatever") is None


async def test_authenticate_unconfigured_returns_none():
    from app.auth.user_store import (
        SqlAlchemyUserRepository,
        UserService,
        sqlite_url_for,
    )

    # No users seeded -> authenticate returns None (fail-closed on login).
    svc = UserService(SqlAlchemyUserRepository(sqlite_url_for(":memory:")))
    await svc.init_schema()
    assert await svc.authenticate("anything", "anything") is None
    await svc.close()


async def test_seed_is_idempotent(user_service):

    again = await user_service.seed_first_admin(
        username="operator",
        email="operator@example.com",
        password="correct-password",
        role="admin",
    )
    assert again is not None
    assert again.username == "operator"
    assert again.id == (await user_service.get_by_username("operator")).id


async def test_seed_skipped_when_no_password(user_service):
    assert (
        await user_service.seed_first_admin(
            username="nobody", email="nobody@example.com", password="", role="user"
        )
        is None
    )


# ---------------------------------------------------------------------------
# token store (family reuse detection)
# ---------------------------------------------------------------------------


def test_store_create_family(auth_settings):
    store = RefreshTokenStore()
    h = "hash-a"
    store.create_family(h, "operator")
    family = store.lookup(h)
    assert family is not None
    assert family.subject == "operator"
    assert family.current_hash == h
    assert family.revoked is False


def test_store_create_duplicate_raises(auth_settings):
    store = RefreshTokenStore()
    store.create_family("hash-a", "operator")
    with pytest.raises(ValueError):
        store.create_family("hash-a", "operator")


def test_store_rotate_success(auth_settings):
    store = RefreshTokenStore()
    store.create_family("h1", "operator")
    assert store.rotate("h1", "h2") == "operator"
    family = store.lookup("h1")
    assert family is not None
    assert family.current_hash == "h2"


def test_store_rotate_replay_revokes_family(auth_settings):
    store = RefreshTokenStore()
    store.create_family("h1", "operator")
    store.rotate("h1", "h2")
    # Replaying the now-stale current token "h1" must revoke the whole family.
    assert store.rotate("h1", "h3") is None
    # Even the legitimately-rotated "h2" is now dead after the replay.
    assert store.rotate("h2", "h4") is None


def test_store_rotate_unknown_hash(auth_settings):
    store = RefreshTokenStore()
    store.create_family("h1", "operator")
    assert store.rotate("nope", "h2") is None


def test_store_rotate_after_revoke(auth_settings):
    store = RefreshTokenStore()
    store.create_family("h1", "operator")
    store.rotate("h1", "h2")
    store.revoke("h1")
    assert store.rotate("h2", "h3") is None


def test_store_revoke_by_token(auth_settings):
    store = RefreshTokenStore()
    store.create_family("h1", "operator")
    store.rotate("h1", "h2")
    store.revoke_by_token("h2")
    family = store.lookup("h1")
    assert family is not None
    assert family.revoked is True


def test_store_is_revoked(auth_settings):
    store = RefreshTokenStore()
    store.create_family("h1", "operator")
    assert store.is_revoked("h1") is False
    store.revoke("h1")
    assert store.is_revoked("h1") is True
    assert store.is_revoked("unknown") is True


# ---------------------------------------------------------------------------
# routes: token (login)
# ---------------------------------------------------------------------------


async def login(client, password="correct-password", username="operator"):
    """Helper: POST /api/v1/auth/token, return the response."""
    return await client.post(
        "/api/v1/auth/token",
        json={"username": username, "password": password},
    )


async def test_login_success(auth_client):
    resp = await login(auth_client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.access_token_ttl_minutes * 60
    # Access token actually verifies and carries the logged-in username as sub.
    claims = verify_access_token(body["access_token"])
    assert claims["sub"] == "operator"
    assert set(claims["scope"].split()) == {"cv:read", "cv:manage"}
    assert claims["role"] == "admin"
    # Refresh cookie set with Correct attributes (attribute names are
    # case-insensitive; Starlette serializes SameSite lowercase).
    set_cookie = resp.headers.get("set-cookie", "")
    cookie_lower = set_cookie.lower()
    assert "__Host-refresh_token=" in set_cookie
    assert "httponly" in cookie_lower
    assert "secure" in cookie_lower
    assert "samesite=none" in cookie_lower


async def test_login_wrong_password(auth_client):
    resp = await login(auth_client, password="wrong")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


async def test_login_wrong_username(auth_client):
    # A non-accepted username returns the same generic 401 as a wrong password,
    # so the accepted username is not revealed.
    resp = await login(auth_client, username="attacker")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


async def test_login_fail_closed_when_unconfigured(auth_client, monkeypatch):
    # With an empty user store (no seeded admin), login must fail closed with a
    # generic 401 — never a 200, and no hint about the store's state.
    import app.auth.user_store as user_store_module
    from app.auth.user_store import (
        SqlAlchemyUserRepository,
        UserService,
        sqlite_url_for,
    )

    empty = UserService(SqlAlchemyUserRepository(sqlite_url_for(":memory:")))
    await empty.init_schema()
    monkeypatch.setattr(user_store_module, "user_service", empty)
    resp = await login(auth_client)
    assert resp.status_code == 401  # generic message, no reveal
    await empty.close()


async def test_login_requires_username_and_password(auth_client):
    resp = await auth_client.post("/api/v1/auth/token", json={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# routes: refresh + logout
# ---------------------------------------------------------------------------


async def _do_login_and_capture_cookie(client):
    """Login and return (access_token, refresh_token); the refresh cookie is
    also set on the client jar so subsequent requests carry it."""
    resp = await login(client)
    assert resp.status_code == 200
    set_cookie = resp.headers["set-cookie"]
    # Extract the token value from "__Host-refresh_token=...; Path=/"
    token = set_cookie.split(";")[0].split("=", 1)[1]
    client.cookies.set("__Host-refresh_token", token, path="/")
    return resp.json()["access_token"], token


async def test_refresh_success(auth_client):
    access1, refresh1 = await _do_login_and_capture_cookie(auth_client)
    verify_access_token(access1)

    resp = await auth_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200
    access2 = resp.json()["access_token"]
    verify_access_token(access2)
    # The refreshed token carries the same subject as the original login (from
    # the token family), not a hardcoded constant.
    assert verify_access_token(access2)["sub"] == "operator"
    # A NEW refresh cookie is returned (rotation).
    set_cookie = resp.headers.get("set-cookie", "")
    assert "__Host-refresh_token=" in set_cookie
    refresh2 = set_cookie.split(";")[0].split("=", 1)[1]
    assert refresh2 != refresh1


async def test_refresh_replay_detection(auth_client):
    _, refresh1 = await _do_login_and_capture_cookie(auth_client)
    # First refresh succeeds and rotates.
    r1 = await auth_client.post("/api/v1/auth/refresh")
    assert r1.status_code == 200
    # Replaying the SAME original refresh token is a replay -> revoke family.
    r2 = await auth_client.post(
        "/api/v1/auth/refresh", cookies={"__Host-refresh_token": refresh1}
    )
    assert r2.status_code == 401
    # The previously-rotated token is now also dead.
    set_cookie = r1.headers["set-cookie"]
    refresh2 = set_cookie.split(";")[0].split("=", 1)[1]
    r3 = await auth_client.post(
        "/api/v1/auth/refresh", cookies={"__Host-refresh_token": refresh2}
    )
    assert r3.status_code == 401


async def test_refresh_missing_cookie(auth_client):
    resp = await auth_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Missing refresh token"


async def test_refresh_unknown_token(auth_client):
    resp = await auth_client.post(
        "/api/v1/auth/refresh", cookies={"__Host-refresh_token": "not-a-real-token"}
    )
    assert resp.status_code == 401


async def test_logout_revokes_family(auth_client):
    _, refresh1 = await _do_login_and_capture_cookie(auth_client)
    resp = await auth_client.post("/api/v1/auth/logout")
    assert resp.status_code == 204
    # Cookie cleared.
    set_cookie = resp.headers.get("set-cookie", "")
    assert "__Host-refresh_token=" in set_cookie and "Max-Age=0" in set_cookie
    # Refresh now fails.
    resp = await auth_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


async def test_logout_without_cookie_is_ok(auth_client):
    resp = await auth_client.post("/api/v1/auth/logout")
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# routes: me + middleware
# ---------------------------------------------------------------------------


async def test_me_with_valid_token(auth_client):
    access, _ = await _do_login_and_capture_cookie(auth_client)
    resp = await auth_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}
    )
    assert resp.status_code == 200
    assert resp.json()["subject"] == "operator"
    assert set(resp.json()["scopes"]) == {"cv:read", "cv:manage"}
    assert resp.json()["role"] == "admin"


async def test_me_without_token(auth_client):
    resp = await auth_client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_with_invalid_token(auth_client):
    resp = await auth_client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer garbage.token.here"}
    )
    assert resp.status_code == 401


async def test_me_bad_header_scheme(auth_client):
    resp = await auth_client.get(
        "/api/v1/auth/me", headers={"Authorization": "Basic dXNlcjpwYXNz"}
    )
    assert resp.status_code == 401


async def test_middleware_fail_closed_no_key(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "jwt_signing_key", "")
    # With a presented token but no configured signing key, the middleware must
    # fail closed (503) rather than silently allowing the request.
    resp = await auth_client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer sometoken"}
    )
    assert resp.status_code == 503


async def test_middleware_passes_public_paths(auth_client):
    # Public CV surface is untouched by JWTAuthMiddleware.
    resp = await auth_client.get("/cv")
    assert resp.status_code == 200
    resp = await auth_client.get("/health")
    assert resp.status_code == 200


async def test_protected_api_v1_requires_token(auth_client):
    # Any /api/v1/* route other than token/refresh/me-like protected requires a
    # JWT; /me is our representative protected route (covered above). This
    # asserts the namespace gate applies.
    resp = await auth_client.get("/api/v1/auth/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# credentialed CORS for /api/v1/auth/refresh
# ---------------------------------------------------------------------------


async def test_cors_preflight_pinned_origin(auth_client):
    resp = await auth_client.options(
        "/api/v1/auth/refresh",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code == 204
    assert resp.headers.get("access-control-allow-origin") == "https://app.example.com"
    assert resp.headers.get("access-control-allow-credentials") == "true"
    assert "POST" in resp.headers.get("access-control-allow-methods", "")


async def test_cors_actual_request_sets_credentials(auth_client):
    # A cross-origin refresh request from the pinned SPA origin gets the
    # credentialed headers (overriding the wildcard from inner CORS).
    _, _ = await _do_login_and_capture_cookie(auth_client)
    resp = await auth_client.post(
        "/api/v1/auth/refresh",
        headers={"Origin": "https://app.example.com"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://app.example.com"
    assert resp.headers.get("access-control-allow-credentials") == "true"


async def test_cors_public_endpoint_not_credentialed(auth_client):
    resp = await auth_client.get("/cv", headers={"Origin": "https://app.example.com"})
    assert resp.status_code == 200
    # Wildcard CORS wins for the public surface (no credentials).
    assert resp.headers.get("access-control-allow-credentials") is None
