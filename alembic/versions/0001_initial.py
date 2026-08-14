"""Initial schema for folders, bookmarks, tags, and jobs.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create core bookmark tables."""
    op.create_table(
        "folders",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "parent_id", sa.Integer(), sa.ForeignKey("folders.id"), nullable=True
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("SYSTIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("SYSTIMESTAMP"),
        ),
    )
    op.create_index("ix_folders_parent_id", "folders", ["parent_id"])

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("SYSTIMESTAMP"),
        ),
        sa.UniqueConstraint("name", name="uq_tags_name"),
    )
    # Oracle unique constraints already index the column list (ORA-01408).

    op.create_table(
        "bookmarks",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "folder_id", sa.Integer(), sa.ForeignKey("folders.id"), nullable=True
        ),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "thumbnail_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("thumbnail_path", sa.String(length=1024), nullable=True),
        sa.Column("thumbnail_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("SYSTIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("SYSTIMESTAMP"),
        ),
    )
    op.create_index("ix_bookmarks_folder_id", "bookmarks", ["folder_id"])

    op.create_table(
        "bookmark_tags",
        sa.Column(
            "bookmark_id",
            sa.Integer(),
            sa.ForeignKey("bookmarks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.Integer(),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("job_type", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("SYSTIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("SYSTIMESTAMP"),
        ),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_scheduled_at", "jobs", ["scheduled_at"])


def downgrade() -> None:
    """Drop core bookmark tables."""
    op.drop_index("ix_jobs_scheduled_at", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("bookmark_tags")
    op.drop_index("ix_bookmarks_folder_id", table_name="bookmarks")
    op.drop_table("bookmarks")
    op.drop_table("tags")
    op.drop_index("ix_folders_parent_id", table_name="folders")
    op.drop_table("folders")
