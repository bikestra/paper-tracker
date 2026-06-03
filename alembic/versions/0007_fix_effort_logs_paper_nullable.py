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
    with op.batch_alter_table("effort_logs", schema=None) as batch_op:
        batch_op.alter_column("paper_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("effort_logs", schema=None) as batch_op:
        batch_op.alter_column("paper_id", existing_type=sa.Integer(), nullable=False)
