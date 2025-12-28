"""Add textbook_id to effort_logs and make paper_id nullable.

Revision ID: 0006_add_textbook_effort_support
Revises: 0005_add_textbooks
Create Date: 2024-12-28
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0006_add_textbook_effort_support"
down_revision = "0005_add_textbooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use batch mode for SQLite/Turso compatibility - this recreates the table
    # which allows us to change paper_id to nullable and add textbook_id
    with op.batch_alter_table(
        "effort_logs",
        schema=None,
        recreate="always",  # Force table recreation for SQLite
        copy_from=sa.Table(
            "effort_logs",
            sa.MetaData(),
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("paper_id", sa.Integer(), nullable=False),  # Old: NOT NULL
            sa.Column("points", sa.Integer(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        ),
    ) as batch_op:
        # Make paper_id nullable
        batch_op.alter_column("paper_id", nullable=True)
        # Add textbook_id column
        batch_op.add_column(sa.Column("textbook_id", sa.Integer(), nullable=True))
        # Create index for textbook_id
        batch_op.create_index(
            "ix_effort_logs_textbook_id",
            ["textbook_id"],
            unique=False,
        )
        # Add foreign key for textbook_id
        batch_op.create_foreign_key(
            "fk_effort_logs_textbook_id",
            "textbooks",
            ["textbook_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("effort_logs", schema=None, recreate="always") as batch_op:
        batch_op.drop_constraint("fk_effort_logs_textbook_id", type_="foreignkey")
        batch_op.drop_index("ix_effort_logs_textbook_id")
        batch_op.drop_column("textbook_id")
        batch_op.alter_column("paper_id", nullable=False)
