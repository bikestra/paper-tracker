"""Add category to effort_logs to support non-paper/textbook activities.

Revision ID: 0015_add_effort_category
Revises: 0014_add_monthly_summaries
Create Date: 2026-10-04
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0015_add_effort_category"
down_revision = "0014_add_monthly_summaries"
branch_labels = None
depends_on = None

effort_category = sa.Enum(
    "PAPER", "TEXTBOOK", "SOFTWARE", "MUSIC", name="effortcategory"
)


def upgrade() -> None:
    effort_category.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "effort_logs",
        sa.Column("category", effort_category, nullable=True),
    )

    # Backfill existing rows from which item they're linked to - all prior
    # effort logs were against either a paper or a textbook.
    op.execute(
        "UPDATE effort_logs SET category = 'TEXTBOOK' WHERE textbook_id IS NOT NULL"
    )
    op.execute("UPDATE effort_logs SET category = 'PAPER' WHERE category IS NULL")

    with op.batch_alter_table("effort_logs", schema=None) as batch_op:
        batch_op.alter_column("category", existing_type=effort_category, nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("effort_logs", schema=None) as batch_op:
        batch_op.drop_column("category")
    effort_category.drop(op.get_bind(), checkfirst=True)
