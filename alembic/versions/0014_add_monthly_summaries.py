"""Add monthly_summaries table for GPT-generated monthly research digests.

Revision ID: 0014_add_monthly_summaries
Revises: 0013_add_openreview_fields
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_add_monthly_summaries"
down_revision = "0013_add_openreview_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monthly_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "year", "month", name="uq_monthly_summary_user_year_month"
        ),
    )
    op.create_index(
        "ix_monthly_summaries_user_id", "monthly_summaries", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_monthly_summaries_user_id")
    op.drop_table("monthly_summaries")
