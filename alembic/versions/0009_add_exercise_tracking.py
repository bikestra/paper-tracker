"""Add exercise tracking tables.

Revision ID: 0009_add_exercise_tracking
Revises: 02e974a65850
Create Date: 2025-02-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_add_exercise_tracking"
down_revision = "02e974a65850"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create exercises table (per-exercise state)
    op.create_table(
        "exercises",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "exercise_type",
            sa.Enum(
                "SQUAT",
                "BENCH_PRESS",
                "PENDLAY_ROW",
                "OVERHEAD_PRESS",
                "DEADLIFT",
                "PULL_UP",
                name="exercisetype",
            ),
            nullable=False,
        ),
        sa.Column("last_top_set_weight", sa.Float(), nullable=True),
        sa.Column("last_top_set_reps", sa.Integer(), nullable=True),
        sa.Column("last_rir", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "exercise_type", name="uq_exercise_user_type"),
    )
    op.create_index("ix_exercises_user_id", "exercises", ["user_id"])

    # Create workouts table
    op.create_table(
        "workouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "workout_type",
            sa.Enum("WORKOUT_A", "WORKOUT_B", name="workouttype"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PLANNING",
                "IN_PROGRESS",
                "COMPLETED",
                "ABANDONED",
                name="workoutstatus",
            ),
            nullable=False,
            server_default="PLANNING",
        ),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workouts_user_id", "workouts", ["user_id"])
    op.create_index("ix_workouts_status", "workouts", ["status"])

    # Create workout_sets table
    op.create_table(
        "workout_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workout_id", sa.Integer(), nullable=False),
        sa.Column(
            "exercise_type",
            sa.Enum(
                "SQUAT",
                "BENCH_PRESS",
                "PENDLAY_ROW",
                "OVERHEAD_PRESS",
                "DEADLIFT",
                "PULL_UP",
                name="exercisetype",
            ),
            nullable=False,
        ),
        sa.Column(
            "set_type",
            sa.Enum("WARMUP", "TOP_SET", "BACK_OFF", name="settype"),
            nullable=False,
        ),
        sa.Column("set_number", sa.Integer(), nullable=False),
        sa.Column("target_weight", sa.Float(), nullable=False),
        sa.Column("target_reps", sa.Integer(), nullable=False),
        sa.Column("actual_weight", sa.Float(), nullable=True),
        sa.Column("actual_reps", sa.Integer(), nullable=True),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["workout_id"], ["workouts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workout_sets_workout_id", "workout_sets", ["workout_id"])

    # Create exercise_results table
    op.create_table(
        "exercise_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workout_id", sa.Integer(), nullable=False),
        sa.Column(
            "exercise_type",
            sa.Enum(
                "SQUAT",
                "BENCH_PRESS",
                "PENDLAY_ROW",
                "OVERHEAD_PRESS",
                "DEADLIFT",
                "PULL_UP",
                name="exercisetype",
            ),
            nullable=False,
        ),
        sa.Column("top_set_weight", sa.Float(), nullable=True),
        sa.Column("top_set_reps", sa.Integer(), nullable=True),
        sa.Column("rir", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["workout_id"], ["workouts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workout_id", "exercise_type", name="uq_exercise_result_workout_exercise"
        ),
    )
    op.create_index(
        "ix_exercise_results_workout_id", "exercise_results", ["workout_id"]
    )

    # Create gpt_conversations table
    op.create_table(
        "gpt_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("workout_id", sa.Integer(), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("gpt_response", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workout_id"], ["workouts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gpt_conversations_user_id", "gpt_conversations", ["user_id"])
    op.create_index(
        "ix_gpt_conversations_workout_id", "gpt_conversations", ["workout_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_gpt_conversations_workout_id")
    op.drop_index("ix_gpt_conversations_user_id")
    op.drop_table("gpt_conversations")

    op.drop_index("ix_exercise_results_workout_id")
    op.drop_table("exercise_results")

    op.drop_index("ix_workout_sets_workout_id")
    op.drop_table("workout_sets")

    op.drop_index("ix_workouts_status")
    op.drop_index("ix_workouts_user_id")
    op.drop_table("workouts")

    op.drop_index("ix_exercises_user_id")
    op.drop_table("exercises")

    # Drop enums
    op.execute("DROP TYPE IF EXISTS workoutstatus")
    op.execute("DROP TYPE IF EXISTS workouttype")
    op.execute("DROP TYPE IF EXISTS settype")
    op.execute("DROP TYPE IF EXISTS exercisetype")
