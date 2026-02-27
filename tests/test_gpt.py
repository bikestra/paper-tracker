"""Tests for GPT workout plan parsing."""

import pytest

from app.gpt import format_exercise_history, parse_workout_plan
from app.models import ExerciseType, SetType


class TestParseWorkoutPlan:
    """Tests for parse_workout_plan()."""

    def test_parse_code_fenced_json(self):
        """Standard happy path with code fences."""
        response = """Here's your workout plan:

```json
{
  "exercises": [
    {
      "exercise": "SQUAT",
      "sets": [
        {"type": "WARMUP", "weight": 45, "reps": 10},
        {"type": "TOP_SET", "weight": 205, "reps": 5},
        {"type": "BACK_OFF", "weight": 180, "reps": 5}
      ],
      "notes": "Top set aim RIR 2-3."
    }
  ]
}
```

Good luck!"""
        plan = parse_workout_plan(response)
        assert plan is not None
        assert len(plan.exercises) == 1
        ex = plan.exercises[0]
        assert ex.exercise == ExerciseType.SQUAT
        assert len(ex.sets) == 3
        assert ex.sets[0].type == SetType.WARMUP
        assert ex.sets[0].weight == 45
        assert ex.sets[1].type == SetType.TOP_SET
        assert ex.sets[1].weight == 205
        assert ex.sets[2].type == SetType.BACK_OFF

    def test_parse_unfenced_json(self):
        """JSON without code fences (the bug case)."""
        response = """Here's the plan:

{
  "exercises": [
    {
      "exercise": "DEADLIFT",
      "sets": [
        {"type": "WARMUP", "weight": 135, "reps": 5},
        {"type": "TOP_SET", "weight": 315, "reps": 5}
      ],
      "notes": "One top set only."
    }
  ]
}

Let me know how it goes."""
        plan = parse_workout_plan(response)
        assert plan is not None
        assert len(plan.exercises) == 1
        assert plan.exercises[0].exercise == ExerciseType.DEADLIFT
        assert len(plan.exercises[0].sets) == 2

    def test_parse_work_set_type(self):
        """WORK_SET maps to TOP_SET."""
        response = """```json
{
  "exercises": [
    {
      "exercise": "BENCH_PRESS",
      "sets": [
        {"type": "WARMUP", "weight": 45, "reps": 10},
        {"type": "WORK_SET", "weight": 185, "reps": 5}
      ]
    }
  ]
}
```"""
        plan = parse_workout_plan(response)
        assert plan is not None
        assert plan.exercises[0].sets[1].type == SetType.TOP_SET

    def test_parse_backoff_variants(self):
        """BACKOFF (no underscore) maps to BACK_OFF."""
        response = """```json
{
  "exercises": [
    {
      "exercise": "SQUAT",
      "sets": [
        {"type": "WARMUP", "weight": 45, "reps": 10},
        {"type": "TOP_SET", "weight": 200, "reps": 5},
        {"type": "BACKOFF", "weight": 170, "reps": 5}
      ]
    }
  ]
}
```"""
        plan = parse_workout_plan(response)
        assert plan is not None
        assert plan.exercises[0].sets[2].type == SetType.BACK_OFF

    def test_parse_exercise_name_normalization(self):
        """Exercise names with spaces/hyphens get normalized."""
        response = """```json
{
  "exercises": [
    {
      "exercise": "OVERHEAD PRESS",
      "sets": [
        {"type": "TOP_SET", "weight": 95, "reps": 5}
      ]
    },
    {
      "exercise": "PULL-UP",
      "sets": [
        {"type": "TOP_SET", "weight": 0, "reps": 8}
      ]
    }
  ]
}
```"""
        plan = parse_workout_plan(response)
        assert plan is not None
        assert len(plan.exercises) == 2
        assert plan.exercises[0].exercise == ExerciseType.OVERHEAD_PRESS
        assert plan.exercises[1].exercise == ExerciseType.PULL_UP

    def test_parse_real_gpt_output(self):
        """Regression test with a realistic GPT response that has nested JSON and WORK_SET."""
        response = """### Workout B Plan

**Squat (B-day)**
Based on your B-day history, last session was 190lb x 5 at RIR 3. Repeating 190lb.

**Overhead Press**
Last session 95lb x 5 at RIR 2. Repeat 95lb.

**Deadlift**
Last session 275lb x 5 at RIR 3. Move up to 285lb.

**Pull-ups**
Bodyweight sets of 8, stopping with 1-2 in reserve.

{
  "exercises": [
    {
      "exercise": "SQUAT",
      "sets": [
        {"type": "WARMUP", "weight": 45, "reps": 10},
        {"type": "WARMUP", "weight": 95, "reps": 5},
        {"type": "WARMUP", "weight": 135, "reps": 3},
        {"type": "WARMUP", "weight": 165, "reps": 2},
        {"type": "WARMUP", "weight": 180, "reps": 1},
        {"type": "TOP_SET", "weight": 190, "reps": 5},
        {"type": "BACK_OFF", "weight": 165, "reps": 5}
      ],
      "notes": "B-day squat. Top set RPE 7 target."
    },
    {
      "exercise": "OVERHEAD_PRESS",
      "sets": [
        {"type": "WARMUP", "weight": 45, "reps": 10},
        {"type": "WARMUP", "weight": 65, "reps": 5},
        {"type": "WARMUP", "weight": 75, "reps": 3},
        {"type": "WARMUP", "weight": 85, "reps": 2},
        {"type": "WARMUP", "weight": 90, "reps": 1},
        {"type": "TOP_SET", "weight": 95, "reps": 5},
        {"type": "BACK_OFF", "weight": 80, "reps": 5}
      ],
      "notes": "Repeat 95lb, RIR 2 last time."
    },
    {
      "exercise": "DEADLIFT",
      "sets": [
        {"type": "WARMUP", "weight": 135, "reps": 5},
        {"type": "WARMUP", "weight": 185, "reps": 3},
        {"type": "WARMUP", "weight": 225, "reps": 2},
        {"type": "WARMUP", "weight": 255, "reps": 1},
        {"type": "WARMUP", "weight": 275, "reps": 1},
        {"type": "TOP_SET", "weight": 285, "reps": 5}
      ],
      "notes": "One top set only. +10lb from last session."
    },
    {
      "exercise": "PULL_UP",
      "sets": [
        {"type": "TOP_SET", "weight": 0, "reps": 8},
        {"type": "TOP_SET", "weight": 0, "reps": 8},
        {"type": "TOP_SET", "weight": 0, "reps": 8}
      ],
      "notes": "Bodyweight. Stop with 1-2 reps in reserve."
    }
  ]
}

Let me know how it goes!"""
        plan = parse_workout_plan(response)
        assert plan is not None
        assert len(plan.exercises) == 4
        assert plan.exercises[0].exercise == ExerciseType.SQUAT
        assert plan.exercises[1].exercise == ExerciseType.OVERHEAD_PRESS
        assert plan.exercises[2].exercise == ExerciseType.DEADLIFT
        assert plan.exercises[3].exercise == ExerciseType.PULL_UP
        # Verify deadlift has no back-off sets
        dl_sets = plan.exercises[2].sets
        assert all(s.type != SetType.BACK_OFF for s in dl_sets)

    def test_parse_no_json_returns_none(self):
        """Graceful failure when no JSON is present."""
        response = "I'd recommend increasing your squat by 5lb next session."
        plan = parse_workout_plan(response)
        assert plan is None

    def test_parse_working_set_type(self):
        """WORKING maps to TOP_SET."""
        response = """```json
{
  "exercises": [
    {
      "exercise": "PENDLAY_ROW",
      "sets": [
        {"type": "WARMUP", "weight": 45, "reps": 10},
        {"type": "WORKING", "weight": 155, "reps": 5}
      ]
    }
  ]
}
```"""
        plan = parse_workout_plan(response)
        assert plan is not None
        assert plan.exercises[0].sets[1].type == SetType.TOP_SET


class TestFormatExerciseHistory:
    """Tests for format_exercise_history()."""

    def test_empty_history(self):
        assert format_exercise_history([]) == "No recent history."

    def test_with_workout_type_labels(self):
        history = [
            {
                "date": "2026-02-24",
                "weight": 220,
                "reps": 5,
                "rir": 3,
                "notes": None,
                "workout_type": "WORKOUT_A",
            },
            {
                "date": "2026-02-22",
                "weight": 190,
                "reps": 5,
                "rir": 2,
                "notes": "Felt heavy",
                "workout_type": "WORKOUT_B",
            },
        ]
        result = format_exercise_history(history)
        assert "(A-day)" in result
        assert "(B-day)" in result
        assert "220lb" in result
        assert "190lb" in result
        assert "Felt heavy" in result

    def test_without_workout_type(self):
        """History without workout_type still works (no label)."""
        history = [
            {"date": "2026-02-24", "weight": 200, "reps": 5, "rir": None, "notes": None},
        ]
        result = format_exercise_history(history)
        assert "(A-day)" not in result
        assert "(B-day)" not in result
        assert "no RIR reported" in result
