"""Fix effort_logs.paper_id to be nullable.

Revision ID: 0007_fix_effort_logs_paper_nullable
Revises: 0006_add_textbook_effort_support
Create Date: 2024-12-28
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0007_fix_effort_logs_paper_nullable"
down_revision = "0006_add_textbook_effort_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use batch mode for SQLite/Turso compatibility - this recreates the table
    # which allows us to change paper_id to nullable
    with op.batch_alter_table(
        "effort_logs",
        schema=None,
        recreate="always",  # Force table recreation for SQLite
        copy_from=sa.Table(
            "effort_logs",
            sa.MetaData(),
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("paper_id", sa.Integer(), nullable=False),  # Current: NOT NULL
            sa.Column("textbook_id", sa.Integer(), nullable=True),
            sa.Column("points", sa.Integer(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        ),
    ) as batch_op:
        # Make paper_id nullable
        batch_op.alter_column("paper_id", nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("effort_logs", schema=None, recreate="always") as batch_op:
        batch_op.alter_column("paper_id", nullable=False)
