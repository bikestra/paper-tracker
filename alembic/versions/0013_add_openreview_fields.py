"""Add OpenReview fields to papers table.

Revision ID: 0013_add_openreview_fields
Revises: 0012_add_pending_arxiv_links
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_add_openreview_fields"
down_revision = "0012_add_pending_arxiv_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("openreview_id", sa.String(50), nullable=True))
    op.add_column(
        "papers", sa.Column("openreview_venue", sa.String(200), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("papers", "openreview_venue")
    op.drop_column("papers", "openreview_id")
