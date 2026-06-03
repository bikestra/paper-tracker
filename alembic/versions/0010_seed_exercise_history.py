"""Seed exercise history from ChatGPT conversation.

Revision ID: 0010_seed_exercise_history
Revises: 0009_add_exercise_tracking
Create Date: 2025-02-21
"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime, timedelta, timezone


revision = "0010_seed_exercise_history"
down_revision = "0009_add_exercise_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Seed historical workout data based on ChatGPT conversation.

    This creates ~6 completed workouts (3 A, 3 B) over the past 3 weeks
    with realistic weights and RIR values for GPT context.
    """
    conn = op.get_bind()

    # Get user_id (assuming single user, ID 1)
    user_id = 1

    # Check if user exists
    result = conn.execute(
        sa.text("SELECT id FROM users WHERE id = :id"), {"id": user_id}
    )
    if not result.fetchone():
        # Create default user if not exists
        conn.execute(
            sa.text(
                "INSERT INTO users (id, email, created_at) VALUES (:id, :email, :created_at)"
            ),
            {
                "id": user_id,
                "email": "default@local",
                "created_at": datetime.now(timezone.utc),
            },
        )

    # Historical workout data based on ChatGPT conversation
    # User was doing modified StrongLifts with top set + back-off, targeting RIR 2-3
    now = datetime.now(timezone.utc)

    # Workout history (most recent first, alternating A/B)
    # Based on conversation: Squat ~215, Bench ~165, Row ~135, OHP ~105, Deadlift ~245
    workouts_data = [
        # Most recent: Workout B (3 days ago)
        {
            "type": "WORKOUT_B",
            "date": now - timedelta(days=3),
            "exercises": [
                {
                    "type": "SQUAT",
                    "weight": 185,
                    "reps": 5,
                    "rir": 3,
                },  # Light squat day
                {"type": "OVERHEAD_PRESS", "weight": 105, "reps": 5, "rir": 2},
                {"type": "DEADLIFT", "weight": 245, "reps": 5, "rir": 2},
            ],
        },
        # 6 days ago: Workout A
        {
            "type": "WORKOUT_A",
            "date": now - timedelta(days=6),
            "exercises": [
                {"type": "SQUAT", "weight": 215, "reps": 5, "rir": 2},
                {"type": "BENCH_PRESS", "weight": 165, "reps": 5, "rir": 2},
                {"type": "PENDLAY_ROW", "weight": 135, "reps": 5, "rir": 3},
            ],
        },
        # 10 days ago: Workout B
        {
            "type": "WORKOUT_B",
            "date": now - timedelta(days=10),
            "exercises": [
                {"type": "SQUAT", "weight": 180, "reps": 5, "rir": 3},
                {"type": "OVERHEAD_PRESS", "weight": 100, "reps": 5, "rir": 2},
                {"type": "DEADLIFT", "weight": 235, "reps": 5, "rir": 3},
            ],
        },
        # 13 days ago: Workout A
        {
            "type": "WORKOUT_A",
            "date": now - timedelta(days=13),
            "exercises": [
                {"type": "SQUAT", "weight": 210, "reps": 5, "rir": 2},
                {"type": "BENCH_PRESS", "weight": 160, "reps": 5, "rir": 2},
                {"type": "PENDLAY_ROW", "weight": 130, "reps": 5, "rir": 3},
            ],
        },
        # 17 days ago: Workout B
        {
            "type": "WORKOUT_B",
            "date": now - timedelta(days=17),
            "exercises": [
                {"type": "SQUAT", "weight": 175, "reps": 5, "rir": 3},
                {"type": "OVERHEAD_PRESS", "weight": 95, "reps": 5, "rir": 3},
                {"type": "DEADLIFT", "weight": 225, "reps": 5, "rir": 2},
            ],
        },
        # 20 days ago: Workout A
        {
            "type": "WORKOUT_A",
            "date": now - timedelta(days=20),
            "exercises": [
                {"type": "SQUAT", "weight": 205, "reps": 5, "rir": 3},
                {"type": "BENCH_PRESS", "weight": 155, "reps": 5, "rir": 2},
                {"type": "PENDLAY_ROW", "weight": 125, "reps": 5, "rir": 4},
            ],
        },
    ]

    # Insert workouts and exercise results
    for workout_data in workouts_data:
        # Insert workout
        result = conn.execute(
            sa.text("""
                INSERT INTO workouts (user_id, workout_type, status, started_at, completed_at)
                VALUES (:user_id, :workout_type, 'COMPLETED', :started_at, :completed_at)
                RETURNING id
            """),
            {
                "user_id": user_id,
                "workout_type": workout_data["type"],
                "started_at": workout_data["date"],
                "completed_at": workout_data["date"] + timedelta(hours=1),
            },
        )
        workout_id = result.fetchone()[0]

        # Insert exercise results
        for ex in workout_data["exercises"]:
            conn.execute(
                sa.text("""
                    INSERT INTO exercise_results
                    (workout_id, exercise_type, top_set_weight, top_set_reps, rir, created_at)
                    VALUES (:workout_id, :exercise_type, :weight, :reps, :rir, :created_at)
                """),
                {
                    "workout_id": workout_id,
                    "exercise_type": ex["type"],
                    "weight": ex["weight"],
                    "reps": ex["reps"],
                    "rir": ex["rir"],
                    "created_at": workout_data["date"],
                },
            )

    # Set current exercise records (latest weights)
    current_exercises = [
        {"type": "SQUAT", "weight": 215, "reps": 5, "rir": 2},
        {"type": "BENCH_PRESS", "weight": 165, "reps": 5, "rir": 2},
        {"type": "PENDLAY_ROW", "weight": 135, "reps": 5, "rir": 3},
        {"type": "OVERHEAD_PRESS", "weight": 105, "reps": 5, "rir": 2},
        {"type": "DEADLIFT", "weight": 245, "reps": 5, "rir": 2},
        {"type": "PULL_UP", "weight": 0, "reps": 8, "rir": 2},  # Bodyweight
    ]

    for ex in current_exercises:
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
    """Remove seeded data."""
    conn = op.get_bind()

    # Delete exercise results, workouts, and exercises for user 1
    conn.execute(
        sa.text("""
        DELETE FROM exercise_results
        WHERE workout_id IN (SELECT id FROM workouts WHERE user_id = 1)
    """)
    )
    conn.execute(sa.text("DELETE FROM workouts WHERE user_id = 1"))
    conn.execute(sa.text("DELETE FROM exercises WHERE user_id = 1"))
