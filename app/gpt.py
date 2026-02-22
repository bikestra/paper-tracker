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


def get_exercises_for_workout(workout_type: models.WorkoutType) -> list[models.ExerciseType]:
    """Get the list of exercises for a workout type."""
    if workout_type == models.WorkoutType.WORKOUT_A:
        return WORKOUT_A_EXERCISES
    return WORKOUT_B_EXERCISES


SYSTEM_PROMPT = """You are a strength training coach helping with a modified StrongLifts 5x5 program.

## Program Overview
- Top set + back-off style (not classic 5x5)
- Target RPE ~7 (RIR 2-3, meaning ~2-3 reps in reserve)
- Time-efficient sessions (~50-60 min)
- Focus on metabolic health (glucose/LDL control), energy, and strength

## Workout Structure
- Workout A: Squat, Bench Press, Pendlay Row
- Workout B: Squat (lighter), Overhead Press, Deadlift, Pull-ups
- Each exercise: warmup ramp → top set → 1-2 back-off sets

## Progression Rules (RPE-based)
- If top set was RIR 4+ (too easy): suggest +5 lb next time (+2.5 for OHP if possible, +10 for deadlift)
- If top set was RIR 2-3 (on target): repeat weight next time
- If top set was RIR 0-1 (too hard): repeat or reduce weight

## Warmup Pattern
Generate warmup ramps that scale with the top set weight:
- Always start with bar (45 lb) for 8-10 reps
- Add 2-4 warmup sets progressively approaching the top set
- Example for 200 lb top set: Bar×8, 95×5, 135×3, 165×2, 185×1, then 200×5 top set

## Special Rules
- Deadlift: ONE top set only (conservative volume)
- B-day squat: lighter/easier than A-day
- Pull-ups: body weight, stop with 1-2 reps in reserve to protect elbows

## Response Format
When generating a workout plan, include a JSON block with the sets:
```json
{
  "exercises": [
    {
      "exercise": "SQUAT",
      "sets": [
        {"type": "WARMUP", "weight": 45, "reps": 10},
        {"type": "WARMUP", "weight": 95, "reps": 5},
        {"type": "WARMUP", "weight": 135, "reps": 3},
        {"type": "TOP_SET", "weight": 200, "reps": 5},
        {"type": "BACK_OFF", "weight": 180, "reps": 5}
      ],
      "notes": "Aim for RIR 2-3 on top set"
    }
  ]
}
```

Always provide practical, actionable advice. When the user reports RIR, use it to inform the next workout's weights.
"""


def format_exercise_history(history: list[dict]) -> str:
    """Format exercise history for GPT context."""
    if not history:
        return "No recent history."

    lines = []
    for h in history:
        rir_str = f"RIR {h['rir']}" if h.get('rir') is not None else "no RIR reported"
        notes_str = f" - {h['notes']}" if h.get('notes') else ""
        lines.append(
            f"- {h['date']}: {h['weight']}lb × {h['reps']} ({rir_str}){notes_str}"
        )
    return "\n".join(lines)


def build_workout_plan_prompt(
    workout_type: models.WorkoutType,
    exercise_history: dict[models.ExerciseType, list[dict]],
    user_context: str | None = None,
) -> str:
    """Build the prompt for generating a workout plan."""
    exercises = get_exercises_for_workout(workout_type)
    workout_name = "Workout A (Squat/Bench/Row)" if workout_type == models.WorkoutType.WORKOUT_A else "Workout B (Squat/OHP/Deadlift/Pull-ups)"

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
        prompt_parts.extend([
            "",
            "## User Context:",
            user_context,
        ])

    prompt_parts.extend([
        "",
        "## Instructions:",
        "1. Based on the history, determine appropriate weights for today",
        "2. Generate warmup ramps, top set, and back-off sets for each exercise",
        "3. Include your reasoning and any notes for the user",
        "4. Return the plan in the JSON format specified in your system prompt",
    ])

    return "\n".join(prompt_parts)


async def call_openai(
    messages: list[dict[str, str]],
    model: str = "gpt-4o-mini",
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
            raise GPTError(f"OpenAI API error: {response.status_code} - {response.text}")

        data = response.json()
        return data["choices"][0]["message"]["content"]


async def stream_openai(
    messages: list[dict[str, str]],
    model: str = "gpt-4o-mini",
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
                raise GPTError(f"OpenAI API error: {response.status_code} - {error_text}")

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


def parse_workout_plan(response: str) -> schemas.GPTWorkoutPlan | None:
    """Parse workout plan JSON from GPT response."""
    # Try to find JSON block in the response
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
    if not json_match:
        # Try without code block
        json_match = re.search(r'\{[^{}]*"exercises"[^{}]*\[.*?\]\s*\}', response, re.DOTALL)

    logger.info(f"JSON match found: {json_match is not None}")

    if not json_match:
        logger.warning("No JSON block found in GPT response")
        return None

    try:
        json_str = json_match.group(1) if json_match.lastindex else json_match.group(0)
        logger.info(f"Parsing JSON: {json_str[:500]}...")
        data = json.loads(json_str)
        logger.info(f"Parsed data keys: {data.keys()}, exercises count: {len(data.get('exercises', []))}")

        exercises = []
        for ex_data in data.get("exercises", []):
            logger.info(f"Processing exercise: {ex_data.get('exercise')}, sets: {len(ex_data.get('sets', []))}")
            sets = []
            for set_data in ex_data.get("sets", []):
                set_type_str = set_data.get("type", "WARMUP").upper()
                # Map string to SetType enum
                set_type = models.SetType[set_type_str]
                sets.append(schemas.GPTWorkoutPlanSet(
                    type=set_type,
                    weight=float(set_data["weight"]),
                    reps=int(set_data["reps"]),
                ))

            ex_type_str = ex_data.get("exercise", "").upper().replace(" ", "_").replace("-", "_")
            logger.info(f"Exercise type string: '{ex_type_str}'")
            exercise_type = models.ExerciseType[ex_type_str]
            exercises.append(schemas.GPTExercisePlan(
                exercise=exercise_type,
                sets=sets,
                notes=ex_data.get("notes"),
            ))

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
    user_prompt = build_workout_plan_prompt(workout_type, exercise_history, user_context)

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
        workout_name = "Workout A" if workout_type == models.WorkoutType.WORKOUT_A else "Workout B"
        context = f"The user is currently doing {workout_name}."

        if exercise_history:
            context += "\n\nRecent exercise history:"
            for ex_type, history in exercise_history.items():
                ex_name = ex_type.value.replace("_", " ").title()
                context += f"\n\n{ex_name}:\n{format_exercise_history(history)}"

        messages.append({"role": "user", "content": f"[Context: {context}]"})
        messages.append({"role": "assistant", "content": "Got it, I understand the context. How can I help?"})

    # Add conversation history
    if conversation_history:
        messages.extend(conversation_history)

    # Add the current message
    messages.append({"role": "user", "content": user_message})

    return await call_openai(messages, max_tokens=1000)
