"""The access-control matrix, derived from the middleware and pinned.

Authorization rules live in several places — role sets, scope prefixes,
public-path exemptions. Reading them tells you how one route is gated;
nobody can hold all of them at once, which is how a route quietly ends up
public. This asks the middleware itself what it enforces for every route
and pins the answer, so a change to any rule shows up as a matrix diff in
review rather than as a surprise in production.

`just access-matrix` prints the same table for sharing.
"""

from __future__ import annotations

import pytest

from services.portfolio.auth.middleware import JWTAuthMiddleware, _is_protected
from services.portfolio.main import app


# Paths that must never require authentication. Registration is here because
# it mints the very credential the others demand; the rest are the login and
# session lifecycle. Anything else appearing here is a bug.
PUBLIC_API_PATHS = {
    "/api/v1/auth/token",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
}

# Path parameters, filled so the middleware sees a realistic path (its rules
# are prefix matches over concrete paths, not route templates).
_PARAM_VALUES = {"{kind}": "cv", "{posting_id}": "1", "{board_id}": "1"}


def _concrete(path: str) -> str:
    for token, value in _PARAM_VALUES.items():
        path = path.replace(token, value)
    return path


def _matrix() -> list[tuple[str, str, bool, bool, str]]:
    """(method, path, authenticated, admin_only, required_scope) per route."""
    schema = app.openapi()
    rows = []
    for path, operations in schema["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method in operations:
            if method.lower() in {"options", "head", "parameters"}:
                continue
            verb = method.upper()
            scope = {
                "type": "http",
                "method": verb,
                "path": _concrete(path),
                "query_string": b"",
            }
            rows.append(
                (
                    verb,
                    path,
                    _is_protected(scope),
                    JWTAuthMiddleware._requires_admin(scope),
                    JWTAuthMiddleware._required_scope(scope) or "",
                )
            )
    return sorted(rows, key=lambda row: (row[1], row[0]))


def render_matrix() -> str:
    """The matrix as a Markdown table, for docs and review."""
    lines = [
        "| Method | Path | Auth | Admin only | Scope |",
        "| --- | --- | --- | --- | --- |",
    ]
    for verb, path, auth, admin, scope in _matrix():
        lines.append(
            f"| {verb} | `{path}` | {'yes' if auth else '**no**'} | "
            f"{'yes' if admin else '-'} | {f'`{scope}`' if scope else '-'} |"
        )
    return "\n".join(lines)


def test_only_credential_routes_are_public():
    """An unauthenticated /api/v1 route is a data leak unless it is a
    credential endpoint. This catches a new one added without a gate."""
    public = {path for _, path, auth, _, _ in _matrix() if not auth}
    assert public == PUBLIC_API_PATHS


def test_document_writes_need_manage_scope_not_admin():
    """Documents are tenant-owned: any user may write their own, so these
    are scope-gated. Were they admin-gated, a registered user could not
    edit their own CV — the whole point of tenancy."""
    writes = {
        (verb, path): (admin, scope)
        for verb, path, _, admin, scope in _matrix()
        if path.startswith("/api/v1/documents/")
    }
    for (verb, path), (admin, scope) in writes.items():
        if verb in {"PUT", "DELETE"}:
            assert not admin, f"{verb} {path} is admin-gated"
            assert scope == "cv:manage", f"{verb} {path} requires {scope!r}"


def test_every_mutation_is_authenticated():
    """No unauthenticated write, whatever else the rules say."""
    for verb, path, auth, _, _ in _matrix():
        if verb in {"POST", "PUT", "PATCH", "DELETE"} and path not in PUBLIC_API_PATHS:
            assert auth, f"{verb} {path} is an unauthenticated mutation"


@pytest.mark.parametrize("verb,path,auth,admin,scope", _matrix())
def test_matrix_row_is_self_consistent(verb, path, auth, admin, scope):
    """A rule that gates on both a role and a scope means two different
    answers to 'who may call this', and the stricter one silently wins."""
    assert not (admin and scope), f"{verb} {path} is gated by both role and scope"
    if not auth:
        assert not admin and not scope, f"{verb} {path} is public yet gated"
