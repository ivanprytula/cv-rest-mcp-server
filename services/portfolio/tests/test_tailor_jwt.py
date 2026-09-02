"""Tests for the JWT-gated tailoring surface (ADR-022, migrating ADR-018).

TailorAuthMiddleware (a dedicated bearer token) was removed; the tailoring
surface now rides the same JWTAuthMiddleware as /api/v1/*:

  - POST /api/v1/cv/tailor requires `Authorization: Bearer <jwt>` for an
    **admin-role** user (the `role` claim, not a scope). It is header-only —
    a `?token=` query param is never accepted.
  - GET /cv/html|pdf|preview WITH a `?tailored=` selector requires a `cv:read`
    JWT, via the Authorization header OR `?token=` (the preview page embeds its
    revision in an iframe that cannot send a header).
  - The public CV surface (no `tailored` selector) is untouched — no JWT needed.

All failures are fail-closed: missing/invalid token -> 401, wrong scope -> 403,
no signing key configured -> 503. These tests drive the real app through an
ASGI client (header-free `auth_client`) and hand-minted tokens.
"""

from __future__ import annotations

from services.portfolio.auth.crypto import sign_access_token
from services.portfolio.settings import settings


def _read_token(scopes, role="user"):
    return sign_access_token("operator", scopes, role=role)


# ---------------------------------------------------------------------------
# POST /api/v1/cv/tailor — mutation, header-only, needs admin ROLE
# ---------------------------------------------------------------------------


async def test_tailor_mutation_requires_valid_jwt(auth_client):
    resp = await auth_client.post("/api/v1/cv/tailor", content="Required: Python")
    assert resp.status_code == 401


async def test_tailor_mutation_header_only_rejects_query_token(
    auth_client, admin_access_token
):
    # A cv:manage token given ONLY in the query string must NOT authorize the
    # mutation — the JWT must never ride a URL (logs the secret).
    resp = await auth_client.post(
        f"/api/v1/cv/tailor?token={admin_access_token}", content="Required: Python"
    )
    assert resp.status_code == 401


async def test_tailor_mutation_requires_admin_role(auth_client):
    # A `user`-role token (default) is denied even though it carries cv:read.
    token = _read_token(["cv:read"])
    resp = await auth_client.post(
        "/api/v1/cv/tailor",
        content="Required: Python",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_tailor_mutation_denies_manage_scope_without_admin_role(auth_client):
    # Scope alone is not enough: the mutation is role-gated, so a `user`-role
    # token with cv:manage scope must STILL be denied.
    token = _read_token(["cv:read", "cv:manage"])
    resp = await auth_client.post(
        "/api/v1/cv/tailor",
        content="Required: Python",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_tailor_mutation_succeeds_with_admin(auth_client, admin_access_token):
    resp = await auth_client.post(
        "/api/v1/cv/tailor",
        content="Required: Python; FastAPI",
        headers={
            "Authorization": f"Bearer {admin_access_token}",
            "content-type": "text/plain",
        },
    )
    # Passes auth and reaches the route handler — a real JD produces 200.
    assert resp.status_code == 200
    assert "saved_to" in resp.json()


# ---------------------------------------------------------------------------
# GET /cv/html|pdf|preview with ?tailored= — read, header or ?token=, cv:read
# ---------------------------------------------------------------------------


async def test_tailored_read_requires_valid_jwt(auth_client):
    resp = await auth_client.get("/cv/html?tailored=latest")
    assert resp.status_code == 401


async def test_tailored_read_accepts_query_token(auth_client, admin_access_token):
    # The preview page's iframe cannot send an Authorization header, so a
    # cv:read token in `?token=` must authorize the revision read. The fresh
    # test store has no revision yet, so the AUTH gate passing shows up as a
    # 404 from the route (not a 401/403).
    resp = await auth_client.get(f"/cv/html?tailored=latest&token={admin_access_token}")
    assert resp.status_code == 404


async def test_tailored_read_requires_cv_read_scope(auth_client):
    token = _read_token(["cv:manage"])
    resp = await auth_client.get(
        "/cv/html?tailored=latest", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


async def test_tailored_read_succeeds_with_read_scope(auth_client):
    token = _read_token(["cv:read"])
    resp = await auth_client.get(
        "/cv/html?tailored=latest", headers={"Authorization": f"Bearer {token}"}
    )
    # No revision exists yet in this fresh test store -> 404 from the route,
    # which still proves the auth gate let it through (not 401/403).
    assert resp.status_code == 404


async def test_empty_tailored_value_not_a_revision_view(auth_client):
    # `?tailored=` with an empty value is not a revision view -> public surface,
    # no auth required.
    resp = await auth_client.get("/cv/html?tailored=")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Fail-closed when auth is not configured
# ---------------------------------------------------------------------------


async def test_tailoring_fail_closed_without_signing_key(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "jwt_signing_key", "")
    resp = await auth_client.get(
        "/cv/html?tailored=latest", headers={"Authorization": "Bearer sometoken"}
    )
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Public surface untouched
# ---------------------------------------------------------------------------


async def test_public_cv_surface_needs_no_jwt(auth_client):
    resp = await auth_client.get("/cv/html")
    assert resp.status_code == 200
    resp = await auth_client.get("/cv/pdf")
    assert resp.status_code in (200, 500)  # 500 only if PDF pipeline hiccups
    resp = await auth_client.get("/cv/preview")
    assert resp.status_code == 200
