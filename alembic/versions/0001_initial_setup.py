"""Initial schema and seed default user"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_initial_setup"
down_revision = None
branch_labels = None
depends_on = None


paper_status = sa.Enum("PLANNED", "READING", "READ", name="paperstatus")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=True, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete=None),
        sa.UniqueConstraint("user_id", "name", name="uq_category_user_name"),
    )
    op.create_index(op.f("ix_categories_user_id"), "categories", ["user_id"], unique=False)

    op.create_table(
        "authors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("orcid", sa.String(length=50), nullable=True),
        sa.Column("arxiv_id", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete=None),
        sa.UniqueConstraint("user_id", "name", name="uq_author_user_name"),
        sa.UniqueConstraint("user_id", "arxiv_id", name="uq_author_user_arxiv_id"),
    )
    op.create_index(op.f("ix_authors_user_id"), "authors", ["user_id"], unique=False)

    op.create_table(
        "papers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("venue_year", sa.String(length=100), nullable=True),
        sa.Column(
            "status",
            paper_status,
            nullable=False,
            server_default=sa.text("'PLANNED'"),
        ),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column(
            "order_index", sa.Integer(), nullable=False, server_default=sa.text("10")
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            server_onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete=None),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete=None),
    )
    op.create_index(op.f("ix_papers_user_id"), "papers", ["user_id"], unique=False)
    op.create_index(op.f("ix_papers_category_id"), "papers", ["category_id"], unique=False)

    op.create_table(
        "paper_authors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column(
            "position", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["author_id"], ["authors.id"], ondelete=None),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete=None),
        sa.UniqueConstraint("paper_id", "author_id", name="uq_paper_author"),
        sa.UniqueConstraint("paper_id", "position", name="uq_paper_author_position"),
    )
    op.create_index(
        op.f("ix_paper_authors_paper_id"), "paper_authors", ["paper_id"], unique=False
    )
    op.create_index(
        op.f("ix_paper_authors_author_id"), "paper_authors", ["author_id"], unique=False
    )

    op.bulk_insert(
        sa.table(
            "users",
            sa.column("id", sa.Integer),
            sa.column("email", sa.String),
        ),
        [{"id": 1, "email": None}],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_paper_authors_author_id"), table_name="paper_authors")
    op.drop_index(op.f("ix_paper_authors_paper_id"), table_name="paper_authors")
    op.drop_table("paper_authors")

    op.drop_index(op.f("ix_papers_category_id"), table_name="papers")
    op.drop_index(op.f("ix_papers_user_id"), table_name="papers")
    op.drop_table("papers")

    op.drop_index(op.f("ix_authors_user_id"), table_name="authors")
    op.drop_table("authors")

    op.drop_index(op.f("ix_categories_user_id"), table_name="categories")
    op.drop_table("categories")

    op.drop_table("users")
    paper_status.drop(op.get_bind())
