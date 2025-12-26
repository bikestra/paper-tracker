"""Add likes column to papers table.

Revision ID: 0002
Revises: 0001
Create Date: 2024-12-25
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_add_likes"
down_revision = "0001_initial_setup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("likes", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("papers", "likes")
