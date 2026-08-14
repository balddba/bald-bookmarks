"""Narrow bookmark description from CLOB to VARCHAR2(256).

Revision ID: 0002_description_varchar
Revises: 0001_initial
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_description_varchar"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Convert bookmarks.description from CLOB to VARCHAR2(256)."""
    op.add_column(
        "bookmarks",
        sa.Column("description_tmp", sa.String(length=256), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE bookmarks SET description_tmp = SUBSTR(description, 1, 256) "
            "WHERE description IS NOT NULL"
        )
    )
    op.drop_column("bookmarks", "description")
    op.alter_column(
        "bookmarks",
        "description_tmp",
        new_column_name="description",
        existing_type=sa.String(length=256),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Restore bookmarks.description as CLOB."""
    op.add_column(
        "bookmarks",
        sa.Column("description_tmp", sa.Text(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE bookmarks SET description_tmp = description "
            "WHERE description IS NOT NULL"
        )
    )
    op.drop_column("bookmarks", "description")
    op.alter_column(
        "bookmarks",
        "description_tmp",
        new_column_name="description",
        existing_type=sa.Text(),
        existing_nullable=True,
    )
