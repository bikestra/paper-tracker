"""Add discovery_sources table for tracking where papers were discovered.

Revision ID: 0004
Revises: 0003_add_effort_logs
Create Date: 2024-12-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_add_discovery_sources"
down_revision = "0003_add_effort_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column(
            "source_type",
            sa.Enum("PAPER", "TEXT", name="discoverysourcetype"),
            nullable=False,
        ),
        sa.Column("source_arxiv_id", sa.String(50), nullable=True),
        sa.Column("source_paper_id", sa.Integer(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"]),
        sa.ForeignKeyConstraint(["source_paper_id"], ["papers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_discovery_sources_paper_id", "discovery_sources", ["paper_id"])
    op.create_index(
        "ix_discovery_sources_source_paper_id", "discovery_sources", ["source_paper_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_discovery_sources_source_paper_id")
    op.drop_index("ix_discovery_sources_paper_id")
    op.drop_table("discovery_sources")
