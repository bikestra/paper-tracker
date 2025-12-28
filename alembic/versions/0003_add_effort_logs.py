"""Add effort_logs table for tracking reading effort.

Revision ID: 0003
Revises: 0002_add_likes
Create Date: 2024-12-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_add_effort_logs"
down_revision = "0002_add_likes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "effort_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_effort_logs_user_id", "effort_logs", ["user_id"])
    op.create_index("ix_effort_logs_paper_id", "effort_logs", ["paper_id"])


def downgrade() -> None:
    op.drop_index("ix_effort_logs_paper_id")
    op.drop_index("ix_effort_logs_user_id")
    op.drop_table("effort_logs")
