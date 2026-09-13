"""event outbox and idempotency keys

Revision ID: f3d8c5a91e47
Revises: e7a2c9f1b6d3
Create Date: 2026-09-13 22:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f3d8c5a91e47"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "e7a2c9f1b6d3"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Deliberately NOT the tenant_isolation policy every other tenant-scoped
# table here gets. The outbox relay must drain every tenant's events in one
# pass, and it connects as cv_app (NOBYPASSRLS) with no request tenant to
# scope to — a tenant_id-matching policy would force a per-tenant loop with
# SET LOCAL for no isolation benefit. tenant_id is carried as *data* here (it
# goes into the event payload), not as an isolation boundary. This departure
# is deliberate; see docs/decisions.md.
#
# idempotency_keys is the opposite case and does get the standard policy: it
# is only ever touched inside a request that already has a tenant.
_IDEMPOTENCY_KEYS_POLICY_SQL = """
CREATE POLICY tenant_isolation ON idempotency_keys
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
    )
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "event_outbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["users.id"],
            name="fk_event_outbox_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_event_outbox"),
    )
    # Partial: the relay only ever scans pending rows, so this stays small
    # even as published rows accumulate for the audit trail.
    op.create_index(
        "ix_event_outbox_pending",
        "event_outbox",
        ["id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column(
            "response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["users.id"],
            name="fk_idempotency_keys_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "key", name="pk_idempotency_keys"),
    )

    op.execute("ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE idempotency_keys FORCE ROW LEVEL SECURITY")
    op.execute(_IDEMPOTENCY_KEYS_POLICY_SQL)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON idempotency_keys")
    op.execute("ALTER TABLE idempotency_keys NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE idempotency_keys DISABLE ROW LEVEL SECURITY")
    op.drop_table("idempotency_keys")

    op.drop_index("ix_event_outbox_pending", table_name="event_outbox")
    op.drop_table("event_outbox")
