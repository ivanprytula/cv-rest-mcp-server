"""job postings tenant and rls

Revision ID: e7a2c9f1b6d3
Revises: c3f81a92d47e
Create Date: 2026-09-12 01:50:00.000000

"""

from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e7a2c9f1b6d3"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "c3f81a92d47e"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Postings are scoped to a tenant by a row-level policy, not only by the
# repository's WHERE clauses — same rationale and mechanism as
# operator_documents (c3f81a92d47e). posting_analyses and phrase_clusters
# are scoped transitively through their FK to job_postings, so they get
# their own policy that joins back rather than a duplicated tenant_id
# column.
_JOB_POSTINGS_POLICY_SQL = """
CREATE POLICY tenant_isolation ON job_postings
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
    )
"""

_POSTING_ANALYSES_POLICY_SQL = """
CREATE POLICY tenant_isolation ON posting_analyses
    USING (
        EXISTS (
            SELECT 1 FROM job_postings p
             WHERE p.id = posting_analyses.posting_id
               AND p.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
        )
    )
"""

_PHRASE_CLUSTERS_POLICY_SQL = """
CREATE POLICY tenant_isolation ON phrase_clusters
    USING (
        EXISTS (
            SELECT 1 FROM job_postings p
             WHERE p.id = phrase_clusters.posting_id
               AND p.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
        )
    )
"""


def upgrade() -> None:
    """Upgrade schema."""
    # owner_id was already present, nullable and unenforced, banked for
    # exactly this migration. Rename it in place rather than add a new
    # column — no data movement needed, just adopt existing NULLs below.
    op.alter_column("job_postings", "owner_id", new_column_name="tenant_id")

    # Adopt existing postings into the lowest-id admin, same convention as
    # operator_documents's tenant backfill.
    op.execute("""
        UPDATE job_postings
           SET tenant_id = (
               SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1
           )
         WHERE tenant_id IS NULL
    """)
    op.execute("DELETE FROM job_postings WHERE tenant_id IS NULL")

    op.alter_column("job_postings", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_job_postings_tenant",
        "job_postings",
        "users",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_job_postings_tenant_id"), "job_postings", ["tenant_id"])

    # source/external_id was unique alone (single-tenant assumption); two
    # tenants tracking the same external posting must not collide.
    op.drop_constraint("uq_job_postings_source_ext", "job_postings", type_="unique")
    op.create_unique_constraint(
        "uq_job_postings_tenant_source_ext",
        "job_postings",
        ["tenant_id", "source", "external_id"],
    )

    op.execute("ALTER TABLE job_postings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE job_postings FORCE ROW LEVEL SECURITY")
    op.execute(_JOB_POSTINGS_POLICY_SQL)

    op.execute("ALTER TABLE posting_analyses ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE posting_analyses FORCE ROW LEVEL SECURITY")
    op.execute(_POSTING_ANALYSES_POLICY_SQL)

    op.execute("ALTER TABLE phrase_clusters ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE phrase_clusters FORCE ROW LEVEL SECURITY")
    op.execute(_PHRASE_CLUSTERS_POLICY_SQL)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON phrase_clusters")
    op.execute("ALTER TABLE phrase_clusters NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE phrase_clusters DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON posting_analyses")
    op.execute("ALTER TABLE posting_analyses NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE posting_analyses DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON job_postings")
    op.execute("ALTER TABLE job_postings NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE job_postings DISABLE ROW LEVEL SECURITY")

    op.drop_constraint(
        "uq_job_postings_tenant_source_ext", "job_postings", type_="unique"
    )
    op.create_unique_constraint(
        "uq_job_postings_source_ext", "job_postings", ["source", "external_id"]
    )

    op.drop_index(op.f("ix_job_postings_tenant_id"), table_name="job_postings")
    op.drop_constraint("fk_job_postings_tenant", "job_postings", type_="foreignkey")
    op.alter_column("job_postings", "tenant_id", nullable=True)
    op.alter_column("job_postings", "tenant_id", new_column_name="owner_id")
