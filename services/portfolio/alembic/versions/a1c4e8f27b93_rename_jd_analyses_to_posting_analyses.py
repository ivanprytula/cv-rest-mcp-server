"""rename jd analyses to posting analyses

Revision ID: a1c4e8f27b93
Revises: 49095e927b5a
Create Date: 2026-09-09 02:15:00.000000

"""

from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a1c4e8f27b93"
down_revision: str | Sequence[str] | None = "49095e927b5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Renames, not drop+create: autogenerate would propose the latter and
    # lose every stored analysis.
    op.rename_table("jd_analyses", "posting_analyses")
    op.execute(
        "ALTER INDEX ix_jd_analyses_analyzer_version "
        "RENAME TO ix_posting_analyses_analyzer_version"
    )
    op.execute(
        "ALTER INDEX ix_jd_analyses_posting_id RENAME TO ix_posting_analyses_posting_id"
    )
    op.execute(
        "ALTER TABLE posting_analyses RENAME CONSTRAINT "
        "uq_jd_analyses_posting_version TO uq_posting_analyses_posting_version"
    )
    # Postgres does not rename these along with the table; left alone they
    # are the only place the old name survives.
    op.execute("ALTER SEQUENCE jd_analyses_id_seq RENAME TO posting_analyses_id_seq")
    op.execute(
        "ALTER TABLE posting_analyses RENAME CONSTRAINT "
        "jd_analyses_pkey TO posting_analyses_pkey"
    )
    op.execute(
        "ALTER TABLE posting_analyses RENAME CONSTRAINT "
        "jd_analyses_posting_id_fkey TO posting_analyses_posting_id_fkey"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "ALTER TABLE posting_analyses RENAME CONSTRAINT "
        "posting_analyses_posting_id_fkey TO jd_analyses_posting_id_fkey"
    )
    op.execute(
        "ALTER TABLE posting_analyses RENAME CONSTRAINT "
        "posting_analyses_pkey TO jd_analyses_pkey"
    )
    op.execute("ALTER SEQUENCE posting_analyses_id_seq RENAME TO jd_analyses_id_seq")
    op.execute(
        "ALTER TABLE posting_analyses RENAME CONSTRAINT "
        "uq_posting_analyses_posting_version TO uq_jd_analyses_posting_version"
    )
    op.execute(
        "ALTER INDEX ix_posting_analyses_posting_id RENAME TO ix_jd_analyses_posting_id"
    )
    op.execute(
        "ALTER INDEX ix_posting_analyses_analyzer_version "
        "RENAME TO ix_jd_analyses_analyzer_version"
    )
    op.rename_table("posting_analyses", "jd_analyses")
