"""Two tenants, one database: neither may see the other's documents.

The repository filters by tenant in Python, and the table has a row-level
policy underneath. This covers both, and — more importantly — covers what
happens when the Python filter is *missing*: the query is issued without it,
and the policy must still return nothing. That is the failure this design
exists to prevent, because a leaked CV comes back as a complete, plausible
answer rather than an error.

Runs as the app role (see `as_app_role`), like production. As `postgres` the
policy is bypassed and every assertion here would pass while proving
nothing.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from services.portfolio.documents.document_repository import (
    SqlAlchemyDocumentRepository,
)
from services.portfolio.documents.document_row import KIND_CV, DocumentRow
from services.portfolio.tenancy import TenantId


pytestmark = pytest.mark.usefixtures("user_service")


@pytest.fixture
async def two_tenants(user_service, session_factory):
    """Two users, each owning a CV, in one database."""
    repo = SqlAlchemyDocumentRepository(session_factory)
    tenants: list[TenantId] = []
    for name in ("alice", "bob"):
        user = await user_service.register(username=name, password="a-long-password")
        assert user is not None
        tenant = TenantId(user.id)
        await repo.put(kind=KIND_CV, payload={"name": name.title()}, tenant_id=tenant)
        tenants.append(tenant)
    return repo, tenants[0], tenants[1]


async def test_each_tenant_reads_only_its_own_document(two_tenants):
    repo, alice, bob = two_tenants

    alice_cv = await repo.get(KIND_CV, tenant_id=alice)
    bob_cv = await repo.get(KIND_CV, tenant_id=bob)

    assert alice_cv is not None and bob_cv is not None
    assert alice_cv.payload == {"name": "Alice"}
    assert bob_cv.payload == {"name": "Bob"}
    assert alice_cv.id != bob_cv.id


async def test_listing_never_includes_another_tenants_documents(two_tenants):
    repo, alice, bob = two_tenants

    for tenant in (alice, bob):
        rows = await repo.list_all(tenant_id=tenant)
        assert [row.tenant_id for row in rows] == [tenant]


async def test_deleting_one_tenants_document_leaves_the_others(two_tenants):
    repo, alice, bob = two_tenants

    assert await repo.delete(KIND_CV, tenant_id=alice) is True

    assert await repo.get(KIND_CV, tenant_id=alice) is None
    assert await repo.get(KIND_CV, tenant_id=bob) is not None


async def test_a_write_cannot_target_another_tenant(two_tenants):
    """Writing Alice's kind while scoped to Bob creates Bob's row, never
    overwrites Alice's — the policy's WITH CHECK equivalent."""
    repo, alice, bob = two_tenants

    await repo.put(kind=KIND_CV, payload={"name": "Bob edited"}, tenant_id=bob)

    alice_cv = await repo.get(KIND_CV, tenant_id=alice)
    assert alice_cv is not None
    assert alice_cv.payload == {"name": "Alice"}


async def test_a_query_without_the_tenant_filter_returns_nothing(
    two_tenants, session_factory
):
    """The point of row-level security.

    This issues the query the repository would produce if someone dropped
    the `WHERE tenant_id = ...` clause. Under the policy it returns no rows;
    without the policy it would return every tenant's CV and the caller
    could not tell.
    """
    _, alice, _ = two_tenants

    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(alice)},
            )
            # Deliberately unfiltered.
            rows = (await session.execute(select(DocumentRow))).scalars().all()

    assert [row.tenant_id for row in rows] == [alice], (
        "an unfiltered query saw another tenant's rows: RLS is not enforced"
    )


async def test_an_unscoped_connection_sees_nothing(two_tenants, session_factory):
    """No tenant set at all is fail-closed, not fail-open — a code path that
    forgets to scope the session reads zero rows rather than all of them."""
    async with session_factory() as session:
        rows = (await session.execute(select(DocumentRow))).scalars().all()

    assert rows == []


class TestStartupRefusesAnRlsBypassingRole:
    """Provisioning is Terraform's job (production) or an initdb script's
    (local), so the app does not repair a bad role — it refuses to start.
    Without this, a role that bypasses the policy is invisible: nothing
    errors, queries just return other tenants' rows.
    """

    async def test_the_app_role_is_accepted(self, session_factory):
        from services.portfolio.tenancy import verify_rls_enforced

        await verify_rls_enforced(session_factory)  # must not raise

    async def test_a_superuser_connection_is_refused(self, _fresh_postgres_url):
        from services.portfolio.db import build_engine, build_session_factory
        from services.portfolio.tenancy import TenantIsolationError, verify_rls_enforced

        # _fresh_postgres_url is the admin (superuser) URL, which is exactly
        # what must be rejected for serving requests.
        admin_factory = build_session_factory(build_engine(_fresh_postgres_url))
        with pytest.raises(TenantIsolationError, match="bypasses row-level security"):
            await verify_rls_enforced(admin_factory)
