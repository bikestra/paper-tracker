"""Add textbooks table.

Revision ID: 0005_add_textbooks
Revises: 0004_add_discovery_sources
Create Date: 2024-12-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_add_textbooks"
down_revision = "0004_add_discovery_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "textbooks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("authors", sa.String(500), nullable=True),
        sa.Column("publisher", sa.String(200), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("isbn", sa.String(20), nullable=True),
        sa.Column("edition", sa.String(50), nullable=True),
        sa.Column("url", sa.String(500), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PLANNED", "READING", "READ", name="textbookstatus"),
            nullable=False,
        ),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("likes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_textbooks_user_id", "textbooks", ["user_id"])
    op.create_index("ix_textbooks_category_id", "textbooks", ["category_id"])
    op.create_index("ix_textbooks_status", "textbooks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_textbooks_status")
    op.drop_index("ix_textbooks_category_id")
    op.drop_index("ix_textbooks_user_id")
    op.drop_table("textbooks")
