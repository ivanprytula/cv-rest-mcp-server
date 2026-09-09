"""tenant documents and rls

Revision ID: c3f81a92d47e
Revises: a1c4e8f27b93
Create Date: 2026-09-09 12:25:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c3f81a92d47e"
down_revision: str | Sequence[str] | None = "a1c4e8f27b93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Documents are scoped to a tenant by a row-level policy, not only by the
# repository's WHERE clauses. A forgotten filter is then an empty result
# instead of another tenant's CV — the app-layer filter stays the primary
# mechanism, this is the backstop for when it is missed.
_POLICY_SQL = """
CREATE POLICY tenant_isolation ON operator_documents
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
    )
"""


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable first: existing rows predate tenancy and must be adopted by
    # the current operator before the column can be NOT NULL.
    op.add_column(
        "operator_documents", sa.Column("tenant_id", sa.BigInteger(), nullable=True)
    )

    # Adopt existing documents into the lowest-id admin — the operator whose
    # data this already is on a single-operator install. If no admin exists
    # (a fresh database), there is nothing to adopt.
    op.execute("""
        UPDATE operator_documents
           SET tenant_id = (
               SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1
           )
         WHERE tenant_id IS NULL
    """)
    # A row that still has no owner cannot be attributed to anyone and would
    # block the NOT NULL below; it is unreachable under RLS anyway.
    op.execute("DELETE FROM operator_documents WHERE tenant_id IS NULL")

    op.alter_column("operator_documents", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_operator_documents_tenant",
        "operator_documents",
        "users",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_operator_documents_tenant_id"),
        "operator_documents",
        ["tenant_id"],
    )

    # `kind` alone was unique, which is precisely the single-tenant
    # assumption: it permitted exactly one CV in the entire installation.
    op.drop_index("ix_operator_documents_kind", table_name="operator_documents")
    op.create_index(op.f("ix_operator_documents_kind"), "operator_documents", ["kind"])
    op.create_unique_constraint(
        "uq_operator_documents_tenant_kind",
        "operator_documents",
        ["tenant_id", "kind"],
    )

    op.execute("ALTER TABLE operator_documents ENABLE ROW LEVEL SECURITY")
    # FORCE so the policy also applies to the table's owner. It does NOT
    # apply to superusers or roles with BYPASSRLS — including Cloud SQL's
    # cloudsqlsuperuser members — which is why the app connects as a role
    # that has neither (see the `cv_rls_app` role below).
    op.execute("ALTER TABLE operator_documents FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY_SQL)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON operator_documents")
    op.execute("ALTER TABLE operator_documents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE operator_documents DISABLE ROW LEVEL SECURITY")
    op.drop_constraint(
        "uq_operator_documents_tenant_kind", "operator_documents", type_="unique"
    )
    op.drop_index(op.f("ix_operator_documents_kind"), table_name="operator_documents")
    op.create_index(
        "ix_operator_documents_kind",
        "operator_documents",
        ["kind"],
        unique=True,
    )
    op.drop_index(
        op.f("ix_operator_documents_tenant_id"), table_name="operator_documents"
    )
    op.drop_constraint(
        "fk_operator_documents_tenant", "operator_documents", type_="foreignkey"
    )
    op.drop_column("operator_documents", "tenant_id")
