"""The tenant a request acts on.

`TenantId` is a distinct type, not an alias, so a plain `int` cannot be
passed where a tenant is expected. That matters because the ids in this
codebase are interchangeable at runtime and catastrophic to confuse: a
posting id or a document id transposed into a tenant argument reads another
tenant's CV and returns it as a complete, plausible answer. The type checker
rejects that at the call site instead.

Only two places construct one — the `uid` claim of a verified access token,
and the operator lookup that install-wide jobs use — so `TenantId(...)`
appearing anywhere else is worth a second look in review.

At runtime this *is* an `int`: `NewType` erases, so SQLAlchemy binding,
Pydantic models and the row-level-security parameter keep working with no
conversion.
"""

from __future__ import annotations

from typing import NewType


TenantId = NewType("TenantId", int)

# The database role the application connects as. Deliberately not a
# superuser and without BYPASSRLS, because row-level security is not
# enforced for either — the tenant policy would be silently inert. Migrations
# and operator work use the admin role instead; only the app uses this one.
# Must match modules/cloud_sql/variables.tf's `database_user` default.
APP_ROLE = "cv_app"


class TenantIsolationError(RuntimeError):
    """The database connection cannot enforce tenant isolation."""


async def verify_rls_enforced(session_factory) -> None:
    """Fail loudly if this connection bypasses row-level security.

    Provisioning the app role correctly is Terraform's job in production and
    an initdb script's locally, so this does not repair anything — it
    refuses to start instead. Without it a misprovisioned role is invisible:
    every query succeeds, every test passes, and the tenant policy silently
    returns other tenants' rows.

    Both attributes matter. A superuser ignores policies outright, and
    BYPASSRLS does the same without the obvious name — Cloud SQL grants it
    through cloudsqlsuperuser membership, so it can arrive unasked for.
    """
    from sqlalchemy import text

    async with session_factory() as session:
        # `current_user` is always a row in pg_roles, so this cannot be empty.
        user, is_super, bypasses_rls = (
            await session.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()

    if is_super or bypasses_rls:
        raise TenantIsolationError(
            f"Database role {user!r} bypasses row-level security "
            f"(superuser={is_super}, bypassrls={bypasses_rls}). "
            f"Connect as {APP_ROLE!r}, which has neither; migrations and "
            "operator work use the superuser instead."
        )
