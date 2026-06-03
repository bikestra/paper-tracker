"""Add most recent Workout B with corrected data.

Revision ID: 0011_add_recent_workout_b
Revises: 0010_seed_exercise_history
Create Date: 2025-02-22
"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime, timedelta, timezone


revision = "0011_add_recent_workout_b"
down_revision = "0010_seed_exercise_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the most recent Workout B with actual recorded data.

    Squat 190lbs RIR 4+, OHP 90lbs RIR 2, Deadlift 240lbs RIR 4, Pull-ups 4/3/3/3
    """
    conn = op.get_bind()
    user_id = 1
    now = datetime.now(timezone.utc)

    # This workout was the most recent (yesterday or today)
    workout_date = now - timedelta(days=1)

    # Insert the workout
    result = conn.execute(
        sa.text("""
            INSERT INTO workouts (user_id, workout_type, status, started_at, completed_at)
            VALUES (:user_id, :workout_type, 'COMPLETED', :started_at, :completed_at)
            RETURNING id
        """),
        {
            "user_id": user_id,
            "workout_type": "WORKOUT_B",
            "started_at": workout_date,
            "completed_at": workout_date + timedelta(hours=1),
        },
    )
    workout_id = result.fetchone()[0]

    # Insert exercise results
    exercises = [
        {"type": "SQUAT", "weight": 190, "reps": 5, "rir": 6},  # RIR 4+ stored as 6
        {"type": "OVERHEAD_PRESS", "weight": 90, "reps": 5, "rir": 2},
        {"type": "DEADLIFT", "weight": 240, "reps": 5, "rir": 4},
        {
            "type": "PULL_UP",
            "weight": 0,
            "reps": 13,
            "rir": 2,
            "notes": "4/3/3/3 reps",
        },  # Total reps across sets
    ]

    for ex in exercises:
        conn.execute(
            sa.text("""
                INSERT INTO exercise_results
                (workout_id, exercise_type, top_set_weight, top_set_reps, rir, notes, created_at)
                VALUES (:workout_id, :exercise_type, :weight, :reps, :rir, :notes, :created_at)
            """),
            {
                "workout_id": workout_id,
                "exercise_type": ex["type"],
                "weight": ex["weight"],
                "reps": ex["reps"],
                "rir": ex["rir"],
                "notes": ex.get("notes"),
                "created_at": workout_date,
            },
        )

    # Update current exercise records with latest values
    for ex in exercises:
        conn.execute(
            sa.text("""
                INSERT INTO exercises
                (user_id, exercise_type, last_top_set_weight, last_top_set_reps, last_rir, created_at)
                VALUES (:user_id, :exercise_type, :weight, :reps, :rir, :created_at)
                ON CONFLICT (user_id, exercise_type) DO UPDATE SET
                    last_top_set_weight = EXCLUDED.last_top_set_weight,
                    last_top_set_reps = EXCLUDED.last_top_set_reps,
                    last_rir = EXCLUDED.last_rir,
                    updated_at = CURRENT_TIMESTAMP
            """),
            {
                "user_id": user_id,
                "exercise_type": ex["type"],
                "weight": ex["weight"],
                "reps": ex["reps"],
                "rir": ex["rir"],
                "created_at": now,
            },
        )


def downgrade() -> None:
    """Remove the added workout."""
    conn = op.get_bind()

    # Find and delete the workout we added (most recent WORKOUT_B)
    conn.execute(
        sa.text("""
        DELETE FROM exercise_results
        WHERE workout_id IN (
            SELECT id FROM workouts
            WHERE user_id = 1 AND workout_type = 'WORKOUT_B'
            ORDER BY started_at DESC
            LIMIT 1
        )
    """)
    )
    conn.execute(
        sa.text("""
        DELETE FROM workouts
        WHERE id IN (
            SELECT id FROM workouts
            WHERE user_id = 1 AND workout_type = 'WORKOUT_B'
            ORDER BY started_at DESC
            LIMIT 1
        )
    """)
    )
