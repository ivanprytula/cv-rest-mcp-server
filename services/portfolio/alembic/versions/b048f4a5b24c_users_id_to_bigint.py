"""users id to bigint

Revision ID: b048f4a5b24c
Revises: d2b7f4194d6a
Create Date: 2026-09-03 16:54:13.512978

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b048f4a5b24c"
down_revision: str | Sequence[str] | None = "d2b7f4194d6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Swap the varchar(36) uuid PK for a `GENERATED ... AS IDENTITY` bigint.

    No FK references `users.id` anywhere in this schema, so the old uuid
    values carry no relational meaning to preserve — drop + recreate rather
    than an in-place ALTER (a varchar UUID string has no meaningful cast to
    an autoincrementing integer). `sa.Identity()` is required here: a bare
    `add_column(..., autoincrement=True)` is silently ignored by Postgres
    outside `create_table` and produces a plain BIGINT with no default at
    all, unlike a `BigInteger, primary_key=True` column declared inline on
    `create_table` (which SQLAlchemy compiles to an identity column for
    you) — `RevisionRow`'s table doesn't need this because it was created
    fresh via `create_table`, not altered after the fact.
    """
    op.drop_constraint("users_pkey", "users", type_="primary")
    op.drop_column("users", "id")
    op.add_column(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
    )
    op.create_primary_key("users_pkey", "users", ["id"])


def downgrade() -> None:
    """Swap the BIGSERIAL PK back for a varchar(36) uuid column.

    Same rationale as upgrade(): no meaningful value mapping back to a uuid,
    so this recreates an empty uuid PK rather than attempting one.
    """
    op.drop_constraint("users_pkey", "users", type_="primary")
    op.drop_column("users", "id")
    op.add_column(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
    )
    op.create_primary_key("users_pkey", "users", ["id"])
