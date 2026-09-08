"""drop jd text and raw payload from job postings

Revision ID: 49095e927b5a
Revises: 3121b3c34e10
Create Date: 2026-09-07 22:41:24.156436

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "49095e927b5a"
down_revision: str | Sequence[str] | None = "3121b3c34e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOTE: autogenerate also proposed `add_column('tracked_boards', 'notes')`
    # here — that's pre-existing local-dev drift unrelated to this change
    # (the column was already added by 4b7a97ce2ef6's CREATE TABLE; this dev
    # DB's copy of that table predates it), not something this migration
    # should touch. Left out deliberately.
    op.drop_column("job_postings", "jd_text")
    op.drop_column("job_postings", "raw_payload")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "job_postings",
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            autoincrement=False,
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "job_postings",
        sa.Column(
            "jd_text", sa.TEXT(), autoincrement=False, nullable=False, server_default=""
        ),
    )
