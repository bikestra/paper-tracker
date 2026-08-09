"""GPT integration for workout planning and coaching."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, AsyncGenerator

import httpx

from . import models, schemas

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


class GPTError(Exception):
    """Error from GPT API."""

    pass


# Exercises for each workout type
WORKOUT_A_EXERCISES = [
    models.ExerciseType.SQUAT,
    models.ExerciseType.BENCH_PRESS,
    models.ExerciseType.PENDLAY_ROW,
]

WORKOUT_B_EXERCISES = [
    models.ExerciseType.SQUAT,
    models.ExerciseType.OVERHEAD_PRESS,
    models.ExerciseType.DEADLIFT,
    models.ExerciseType.PULL_UP,
]


def get_exercises_for_workout(
    workout_type: models.WorkoutType,
) -> list[models.ExerciseType]:
    """Get the list of exercises for a workout type."""
    if workout_type == models.WorkoutType.WORKOUT_A:
        return WORKOUT_A_EXERCISES
    return WORKOUT_B_EXERCISES


SYSTEM_PROMPT = """You are a strength training coach helping with a modified StrongLifts 5x5 program optimized for time efficiency and metabolic health.

## Program Overview
- Style: Top set + 1–2 back-off sets (not classic 5x5)
- Intensity target: Top set ~RPE 7 (RIR 2–3)
- Session length: ~50–60 minutes
- Priorities: metabolic health (glucose/LDL) → energy/cognition → appearance → strength/proficiency

## Workout Structure
- Workout A: Squat, Bench Press, Pendlay Row
- Workout B: Squat (lighter/easier), Overhead Press, Deadlift (top set only), Pull-ups
- For each barbell lift: warm-up ramp → top set → back-off set(s)

## Progression Rules (RPE-based)
Decide "today's" top set using the most recent comparable session for that lift.
- If last top set was RIR 4+: increase next time
  - +5 lb for squat/bench/row, +10 lb deadlift, +2.5 lb OHP if possible (otherwise +5)
- If last top set was RIR 2–3: repeat same weight
- If last top set was RIR 0–1: repeat or reduce 5–10 lb (and flag technique/fatigue)

## Back-off Set Rules
Purpose: accumulate quality volume without pushing fatigue too high.
- Default: 1 back-off set of 5 at ~85–90% of top set (rounded to available plates)
- If the top set was upper end of target (RIR 2) or you're short on time: one back-off only
- If the top set was easy (RIR 3–4) and time allows: two back-off sets at the same weight
- Deadlift special case: NO back-off sets (top set only)

## Warm-up Ramp Algorithm (smooth transitions)
Warm-ups should gradually approach the top set with no abrupt jumps.

### General principles
- Start with bar x 8–10 for squat/bench/row/OHP (deadlift may start at 95 if bar feels too light, but still include bar if user prefers)
- Use increasing weights + decreasing reps, ending with at least one near-top single
- Keep warm-ups snappy (rest ~60–120s), save longer rests for top/back-off

### Warm-up templates (percent-based)
Let T = top set weight.

**For Squat / Deadlift** (heavier, tolerant of bigger jumps):
- Bar x 8–10
- ~40% T x 5
- ~60% T x 3
- ~75% T x 2
- ~85% T x 1
- ~92–95% T x 1
- Then top set

**For Bench / OHP / Pendlay Row** (more sensitive, smaller jumps):
- Bar x 8–10
- ~35–40% T x 5
- ~55–60% T x 3–5
- ~70% T x 3
- ~80% T x 2
- ~87–90% T x 1
- ~92–95% T x 1
- Then top set

### Bridge rule (prevents abrupt transitions)
If any warm-up jump is >15% of T or >30 lb (bench/row) / >40 lb (squat/deadlift), insert an extra warm-up set between them (usually 1–3 reps).

### Rounding & practicality
- Round warm-up weights to what is realistically loadable with the user's plates.
- If the computed plan creates too many warm-up sets, you may drop the earliest mid-percent set (not the near-top singles).

## Special Rules
- Deadlift: ONE top set only
- Pendlay Row: After warm-ups, perform 3×5 at the same work weight (no back-off). Select weight so Set 1 is RIR 2–3. If form or bar speed degrades in later sets, reduce 5–10 lb for remaining sets.
- B-day squat: Use B-day squat history (not A-day) for progression decisions.
  Typical B-day top set is ~85–90% of the current A-day top set.
  Apply the same RPE-based progression rules, but only comparing against previous B-day sessions.
- Pull-ups: stop with 1–2 reps in reserve to protect elbows/shoulders
- If the user reports joint pain or technique breakdown, prioritize load reduction and technique notes.

## Response Format
When generating a workout plan:
1. Brief reasoning for today's top set + back-off selection for each lift
2. Provide a JSON block:

```json
{
  "exercises": [
    {
      "exercise": "SQUAT",
      "sets": [
        {"type": "WARMUP", "weight": 45, "reps": 10},
        {"type": "WARMUP", "weight": 95, "reps": 5},
        {"type": "WARMUP", "weight": 135, "reps": 3},
        {"type": "WARMUP", "weight": 165, "reps": 2},
        {"type": "WARMUP", "weight": 185, "reps": 1},
        {"type": "WARMUP", "weight": 195, "reps": 1},
        {"type": "TOP_SET", "weight": 205, "reps": 5},
        {"type": "BACK_OFF", "weight": 180, "reps": 5}
      ],
      "notes": "Top set aim RIR 2–3. Back-off ~85–90%."
    }
  ]
}
```

Valid exercise names (use exactly): SQUAT, BENCH_PRESS, PENDLAY_ROW, OVERHEAD_PRESS, DEADLIFT, PULL_UP
Valid set types (use exactly): WARMUP, TOP_SET, BACK_OFF
For pull-ups: use TOP_SET for each set.
IMPORTANT: Always wrap the JSON in ```json ... ``` code fences.

Always provide practical, actionable notes. When the user reports RIR, use it to update the next workout's weights.
"""


def format_exercise_history(history: list[dict]) -> str:
    """Format exercise history for GPT context."""
    if not history:
        return "No recent history."

    lines = []
    for h in history:
        wt = h.get("workout_type", "")
        day_label = (
            " (A-day)" if wt == "WORKOUT_A" else " (B-day)" if wt == "WORKOUT_B" else ""
        )
        rir_str = f"RIR {h['rir']}" if h.get("rir") is not None else "no RIR reported"
        notes_str = f" - {h['notes']}" if h.get("notes") else ""
        lines.append(
            f"- {h['date']}{day_label}: {h['weight']}lb × {h['reps']} ({rir_str}){notes_str}"
        )
    return "\n".join(lines)


def build_workout_plan_prompt(
    workout_type: models.WorkoutType,
    exercise_history: dict[models.ExerciseType, list[dict]],
    user_context: str | None = None,
) -> str:
    """Build the prompt for generating a workout plan."""
    exercises = get_exercises_for_workout(workout_type)
    workout_name = (
        "Workout A (Squat/Bench/Row)"
        if workout_type == models.WorkoutType.WORKOUT_A
        else "Workout B (Squat/OHP/Deadlift/Pull-ups)"
    )

    prompt_parts = [
        f"Generate a detailed workout plan for {workout_name}.",
        "",
        "## Recent History by Exercise:",
    ]

    for ex in exercises:
        ex_name = ex.value.replace("_", " ").title()
        history = exercise_history.get(ex, [])
        prompt_parts.append(f"\n### {ex_name}")
        prompt_parts.append(format_exercise_history(history))

    if user_context:
        prompt_parts.extend(
            [
                "",
                "## User Context:",
                user_context,
            ]
        )

    prompt_parts.extend(
        [
            "",
            "## Instructions:",
            "1. Based on the history, determine appropriate weights for today",
            "2. Generate warmup ramps, top set, and back-off sets for each exercise",
            "3. Include your reasoning and any notes for the user",
            "4. Return the plan in the JSON format specified in your system prompt",
        ]
    )

    return "\n".join(prompt_parts)


async def call_openai(
    messages: list[dict[str, str]],
    model: str = "gpt-4o",
    max_tokens: int = 2000,
    temperature: float = 0.7,
) -> str:
    """Make an async call to OpenAI API."""
    if not OPENAI_API_KEY:
        raise GPTError("OPENAI_API_KEY not configured")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=60.0,
        )

        if response.status_code != 200:
            raise GPTError(
                f"OpenAI API error: {response.status_code} - {response.text}"
            )

        data = response.json()
        return data["choices"][0]["message"]["content"]


async def stream_openai(
    messages: list[dict[str, str]],
    model: str = "gpt-4o",
    max_tokens: int = 2000,
    temperature: float = 0.7,
) -> AsyncGenerator[str, None]:
    """Stream responses from OpenAI API."""
    if not OPENAI_API_KEY:
        raise GPTError("OPENAI_API_KEY not configured")

    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True,
            },
            timeout=120.0,
        ) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                raise GPTError(
                    f"OpenAI API error: {response.status_code} - {error_text}"
                )

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]  # Remove "data: " prefix
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue


SET_TYPE_MAP: dict[str, models.SetType] = {
    "WARMUP": models.SetType.WARMUP,
    "WARM_UP": models.SetType.WARMUP,
    "TOP_SET": models.SetType.TOP_SET,
    "BACK_OFF": models.SetType.BACK_OFF,
    "BACKOFF": models.SetType.BACK_OFF,
    "WORK_SET": models.SetType.TOP_SET,
    "WORKING": models.SetType.TOP_SET,
}


def _extract_json_by_braces(text: str) -> str | None:
    """Extract a JSON object containing 'exercises' using brace matching."""
    idx = text.find('"exercises"')
    if idx == -1:
        return None
    # Walk backward to find the opening brace
    start = text.rfind("{", 0, idx)
    if start == -1:
        return None
    # Walk forward counting braces to find the matching close
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_workout_plan(response: str) -> schemas.GPTWorkoutPlan | None:
    """Parse workout plan JSON from GPT response."""
    # Try to find JSON block in code fences first
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", response, re.DOTALL)

    if json_match:
        json_str = json_match.group(1)
    else:
        # Fall back to brace-matching extraction
        json_str = _extract_json_by_braces(response)

    logger.info(f"JSON extraction found: {json_str is not None}")

    if not json_str:
        logger.warning("No JSON block found in GPT response")
        return None

    try:
        logger.info(f"Parsing JSON: {json_str[:500]}...")
        data = json.loads(json_str)
        logger.info(
            f"Parsed data keys: {data.keys()}, exercises count: {len(data.get('exercises', []))}"
        )

        exercises = []
        for ex_data in data.get("exercises", []):
            logger.info(
                f"Processing exercise: {ex_data.get('exercise')}, sets: {len(ex_data.get('sets', []))}"
            )
            sets = []
            for set_data in ex_data.get("sets", []):
                set_type_str = set_data.get("type", "WARMUP").upper().strip()
                set_type = SET_TYPE_MAP.get(set_type_str, models.SetType.TOP_SET)
                sets.append(
                    schemas.GPTWorkoutPlanSet(
                        type=set_type,
                        weight=float(set_data["weight"]),
                        reps=int(set_data["reps"]),
                    )
                )

            ex_type_str = (
                ex_data.get("exercise", "").upper().replace(" ", "_").replace("-", "_")
            )
            logger.info(f"Exercise type string: '{ex_type_str}'")
            exercise_type = models.ExerciseType[ex_type_str]
            exercises.append(
                schemas.GPTExercisePlan(
                    exercise=exercise_type,
                    sets=sets,
                    notes=ex_data.get("notes"),
                )
            )

        logger.info(f"Total exercises parsed: {len(exercises)}")
        return schemas.GPTWorkoutPlan(exercises=exercises)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        # Log error but return None so we can still show the text response
        logger.error(f"Failed to parse workout plan JSON: {e}")
        return None


async def generate_workout_plan(
    workout_type: models.WorkoutType,
    exercise_history: dict[models.ExerciseType, list[dict]],
    user_context: str | None = None,
) -> tuple[str, schemas.GPTWorkoutPlan | None]:
    """Generate a workout plan using GPT.

    Returns:
        Tuple of (full GPT response text, parsed workout plan or None)
    """
    user_prompt = build_workout_plan_prompt(
        workout_type, exercise_history, user_context
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    response = await call_openai(messages)
    plan = parse_workout_plan(response)

    return response, plan


async def chat_with_coach(
    user_message: str,
    workout_type: models.WorkoutType | None = None,
    exercise_history: dict[models.ExerciseType, list[dict]] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> str:
    """Chat with the GPT coach mid-workout or for general questions.

    Args:
        user_message: The user's message/question
        workout_type: Current workout type (if in a workout)
        exercise_history: Recent exercise history for context
        conversation_history: Previous messages in this conversation

    Returns:
        GPT response text
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add context about current workout if available
    if workout_type:
        workout_name = (
            "Workout A" if workout_type == models.WorkoutType.WORKOUT_A else "Workout B"
        )
        context = f"The user is currently doing {workout_name}."

        if exercise_history:
            context += "\n\nRecent exercise history:"
            for ex_type, history in exercise_history.items():
                ex_name = ex_type.value.replace("_", " ").title()
                context += f"\n\n{ex_name}:\n{format_exercise_history(history)}"

        messages.append({"role": "user", "content": f"[Context: {context}]"})
        messages.append(
            {
                "role": "assistant",
                "content": "Got it, I understand the context. How can I help?",
            }
        )

    # Add conversation history
    if conversation_history:
        messages.extend(conversation_history)

    # Add the current message
    messages.append({"role": "user", "content": user_message})

    return await call_openai(messages, max_tokens=1000)


MONTHLY_SUMMARY_SYSTEM_PROMPT = """You are an assistant that writes a monthly research-reading digest for a user who tracks academic papers they read and log effort against.

You will be given:
- The papers the user engaged with this month (title, abstract, personal notes, effort points, and any notes logged with each reading session)
- This month's total effort points, plus the effort totals for the trailing 3 months for comparison
- The user's own summaries from prior months (if available), to compare against

Write a digest covering:
1. The main research themes/topics the user engaged with this month, grounded in the specific papers provided (mention titles or topics concretely, don't be generic).
2. How this month's effort compares to the trailing 3 months (more/less active, steady, etc.), referencing the actual numbers given.
3. How the user's research interests have shifted compared to prior months' summaries, if any were provided — what's new, what's continuing, what dropped off. If no prior summaries are available, skip this point.

Write 3-5 short paragraphs of plain prose. Do not use markdown headers, bullet lists, or JSON — just clear, direct paragraphs a person would enjoy reading as a monthly recap.
"""


def format_month_papers(papers: list[dict]) -> str:
    """Format a month's papers (with effort data) for GPT context."""
    if not papers:
        return "No papers with logged effort this month."

    lines = []
    for p in papers:
        abstract = (p.get("abstract") or "").strip()
        if len(abstract) > 600:
            abstract = abstract[:600] + "..."
        lines.append(f"- {p['title']} ({p['total_points']} effort pts)")
        if abstract:
            lines.append(f"  Abstract: {abstract}")
        if p.get("notes"):
            lines.append(f"  Paper notes: {p['notes']}")
        if p.get("log_notes"):
            lines.append(f"  Session notes: {'; '.join(p['log_notes'])}")
    return "\n".join(lines)


def format_effort_trend(trend: list[tuple[str, int]]) -> str:
    """Format trailing-month effort totals for GPT context."""
    if not trend:
        return "No prior effort data."
    return "\n".join(f"- {label}: {points} pts" for label, points in trend)


def build_monthly_summary_prompt(
    month_label: str,
    papers: list[dict],
    effort_this_month: int,
    effort_trend: list[tuple[str, int]],
    prev_summaries: list[str],
) -> str:
    """Build the prompt for generating a monthly research summary."""
    prompt_parts = [
        f"Generate a research digest for {month_label}.",
        "",
        f"## Papers engaged with in {month_label} ({effort_this_month} total effort pts):",
        format_month_papers(papers),
        "",
        "## Effort trend (trailing months):",
        format_effort_trend(effort_trend),
    ]

    if prev_summaries:
        prompt_parts.extend(
            [
                "",
                "## Prior months' summaries (most recent first):",
                *[f"\n{s}" for s in prev_summaries],
            ]
        )

    prompt_parts.extend(
        [
            "",
            "## Instructions:",
            "Write the digest as described in your system prompt.",
        ]
    )

    return "\n".join(prompt_parts)


async def generate_monthly_summary(
    month_label: str,
    papers: list[dict],
    effort_this_month: int,
    effort_trend: list[tuple[str, int]],
    prev_summaries: list[str],
) -> str:
    """Generate a monthly research-interest summary using GPT.

    Returns the raw text response (no structured parsing needed).
    """
    user_prompt = build_monthly_summary_prompt(
        month_label, papers, effort_this_month, effort_trend, prev_summaries
    )

    messages = [
        {"role": "system", "content": MONTHLY_SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    return await call_openai(messages, max_tokens=900)
