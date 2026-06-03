"""Add pending_arxiv_links table.

Revision ID: 0012_add_pending_arxiv_links
Revises: 0011_add_recent_workout_b
Create Date: 2026-05-31
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_add_pending_arxiv_links"
down_revision = "0011_add_recent_workout_b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_arxiv_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("url_or_id", sa.String(length=500), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pending_arxiv_links_user_id", "pending_arxiv_links", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_pending_arxiv_links_user_id", table_name="pending_arxiv_links")
    op.drop_table("pending_arxiv_links")
