"""cleanup_invalid_authors

Revision ID: 02e974a65850
Revises: 0007_fix_effort_logs_paper_nullable
Create Date: 2025-01-01
"""

from alembic import op
import sqlalchemy as sa

revision = "02e974a65850"
down_revision = "0007_fix_effort_logs_paper_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Delete paper_authors links for invalid authors (names that are just punctuation)
    op.execute("""
        DELETE FROM paper_authors
        WHERE author_id IN (
            SELECT id FROM authors
            WHERE TRIM(name) = ''
               OR TRIM(name) = ':'
               OR TRIM(name) = '.'
               OR TRIM(name) = ';'
               OR TRIM(name) = ','
        )
    """)

    # Delete the invalid authors
    op.execute("""
        DELETE FROM authors
        WHERE TRIM(name) = ''
           OR TRIM(name) = ':'
           OR TRIM(name) = '.'
           OR TRIM(name) = ';'
           OR TRIM(name) = ','
    """)


def downgrade() -> None:
    # Data migration - cannot be undone
    pass
