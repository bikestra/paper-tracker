"""Add CASUAL_READING to effort_logs.category for logging non-paper reading.

Revision ID: 0017_add_casual_reading_category
Revises: 0016_add_work_effort_category
Create Date: 2026-10-05
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0017_add_casual_reading_category"
down_revision = "0016_add_work_effort_category"
branch_labels = None
depends_on = None

old_values = ("PAPER", "TEXTBOOK", "SOFTWARE", "MUSIC", "WORK")
new_values = old_values + ("CASUAL_READING",)

old_enum = sa.Enum(*old_values, name="effortcategory")
new_enum = sa.Enum(*new_values, name="effortcategory")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Postgres enum types need a new value added explicitly; this must
        # run outside the migration's transaction block.
        with op.get_context().autocommit_block():
            op.execute(
                "ALTER TYPE effortcategory ADD VALUE IF NOT EXISTS 'CASUAL_READING'"
            )
    else:
        # SQLite enums are a CHECK constraint, not a real type - recreate
        # the column with the widened constraint.
        with op.batch_alter_table("effort_logs", schema=None) as batch_op:
            batch_op.alter_column(
                "category",
                existing_type=old_enum,
                type_=new_enum,
            )


def downgrade() -> None:
    bind = op.get_bind()
    # Reassign any CASUAL_READING entries before narrowing the type back down.
    op.execute(
        "UPDATE effort_logs SET category = 'SOFTWARE' WHERE category = 'CASUAL_READING'"
    )

    if bind.dialect.name == "postgresql":
        # Postgres cannot drop a single enum value in place; rebuild the type.
        op.execute("ALTER TYPE effortcategory RENAME TO effortcategory_old")
        old_enum.create(bind, checkfirst=True)
        op.execute(
            "ALTER TABLE effort_logs ALTER COLUMN category "
            "TYPE effortcategory USING category::text::effortcategory"
        )
        op.execute("DROP TYPE effortcategory_old")
    else:
        with op.batch_alter_table("effort_logs", schema=None) as batch_op:
            batch_op.alter_column(
                "category",
                existing_type=new_enum,
                type_=old_enum,
            )
