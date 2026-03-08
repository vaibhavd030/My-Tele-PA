"""Entity extraction node — the core intelligence of the agent.

Uses Instructor to enforce GPT-4o returns a validated ExtractedData Pydantic model.
Handles partial data gracefully for the clarification loop downstream.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from life_os.agent.state import AgentState
from life_os.config.clients import calculate_cost, get_instructor_client
from life_os.config.settings import settings
from life_os.models.wellness import ExtractedData

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "extract.txt").read_text()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def _call_llm(
    text: str, today: date, chat_history: str = ""
) -> tuple[ExtractedData, int, float]:
    """Call GPT-4o with Instructor to extract structured wellness data.

    Args:
        text: The raw user message to extract from.
        today: Current date for resolving relative references like 'today'.
        chat_history: String representation of recent conversation turns to prevent duplicates.

    Returns:
        Tuple of (ExtractedData, tokens_used, estimated_cost_usd).

    Raises:
        instructor.exceptions.InstructorRetryException: After 3 failed
            validation attempts.
    """
    result, raw_response = await get_instructor_client().chat.completions.create_with_completion(
        model=settings.openai_model,
        response_model=ExtractedData,
        max_retries=2,  # Instructor internal retries on validation fail
        messages=[
            {
                "role": "system",
                "content": (
                    _SYSTEM_PROMPT.format(today=today.isoformat())
                    + "\n\nRecent Chat History (Use this to avoid extracting duplicate information "
                    "if the user is just repeating themselves):\n" + chat_history
                ),
            },
            {"role": "user", "content": text},
        ],
    )
    tokens, cost = calculate_cost(raw_response.usage)
    return result, tokens, cost


async def run(state: AgentState) -> AgentState:
    """Extract structured wellness data from the user message.

    Merges new extraction results with any entities already collected
    in previous clarification turns (does not overwrite confirmed data).

    Args:
        state: Current agent state.

    Returns:
        Updated state with entities and missing_fields populated.
    """
    log.info("extracting_entities", user_id=state["user_id"])

    # ── Check clarification TTL ───────────────────────────────────────────
    now_ts = datetime.now(UTC).timestamp()
    last_ts = state.get("last_interaction_ts")
    is_clarifying = bool(state.get("missing_fields"))
    if is_clarifying and last_ts and (now_ts - last_ts > 1800):
        log.info("clarification_ttl_expired", user_id=state["user_id"])
        state["missing_fields"] = []
        is_clarifying = False

    if is_clarifying:
        history = state.get("chat_history", [])
        history_str = "\n".join([f"{msg.type}: {msg.content}" for msg in history[-5:]])
    else:
        history_str = ""

    extracted, tokens, cost = await _call_llm(
        text=state["raw_input"], today=date.today(), chat_history=history_str
    )

    existing = state.get("entities", {}) if is_clarifying else {}

    # serialize ALL Pydantic objects -> plain dicts for msgpack
    serialized: dict[str, Any] = {}
    
    # Do this safely instead of using dict comprehension to avoid wiping nested objects
    try:
        dumped = extracted.model_dump(mode="json", exclude_none=True)
    except AttributeError:
        # Fallback for mocked objects in tests
        dumped = {}
        for k in type(extracted).model_fields if hasattr(type(extracted), "model_fields") else extracted.__dict__:
            v = getattr(extracted, k, None)
            if v is not None:
                if hasattr(v, "model_dump"):
                    dumped[k] = v.model_dump(mode="json", exclude_none=True)
                elif isinstance(v, list):
                    dumped[k] = [
                        item.model_dump(mode="json", exclude_none=True) if hasattr(item, "model_dump") else item
                        for item in v
                    ]
                else:
                    dumped[k] = v
                    
    # Merge strategy
    if is_clarifying:
        serialized = existing.copy()
        
        def _deep_set(obj: Any, key: str, val: Any) -> None:
            if isinstance(obj, dict):
                for k, v in list(obj.items()):
                    if k == key and v is None:
                        obj[k] = val
                    elif isinstance(v, (dict, list)):
                        _deep_set(v, key, val)
            elif isinstance(obj, list):
                for item in obj:
                    _deep_set(item, key, val)

        for field in state.get("missing_fields", []):
            mapped_field = field.replace(" ", "_")
            if mapped_field == "body_part": mapped_field = "body_parts"
            if mapped_field == "wake_up_time": mapped_field = "wake_hour"
            if mapped_field == "exercise_duration": mapped_field = "duration_minutes"
            
            for k, nv in dumped.items():
                if isinstance(nv, list):
                    for item in nv:
                        if isinstance(item, dict) and item.get(mapped_field) is not None:
                            _deep_set(serialized, mapped_field, item[mapped_field])
                elif isinstance(nv, dict) and nv.get(mapped_field) is not None:
                    _deep_set(serialized, mapped_field, nv[mapped_field])
                    
        # Add new keys that didn't exist before
        for k, nv in dumped.items():
            if k not in serialized:
                serialized[k] = nv
    else:
        serialized = dumped


    # ── Post-process filters ──────────────────────────────────────────────
    # Sometimes the LLM stubbornly categorizes meditation as an "other" exercise.
    if "exercise" in serialized and isinstance(serialized["exercise"], list):
        filtered_exercise = []
        for ex in serialized["exercise"]:
            if isinstance(ex, dict) and ex.get("exercise_type") == "other":
                notes = str(ex.get("notes", "")).lower()
                if "meditat" in notes or "cleaning" in notes or "sitting" in notes:
                    continue  # drop it
            filtered_exercise.append(ex)
        serialized["exercise"] = filtered_exercise

    # ── Missing-field checks (work on serialized plain dicts) ─────────────
    # Only report a field as missing if:
    # 1. It is genuinely absent in the merged entity, AND
    # 2. It was NOT already asked in the previous clarification turn
    #    (if it was asked and still missing, the LLM didn't extract it from
    #     the user's reply — we will give it one more chance via the prompt,
    #     but cap re-asking using clarification_count in graph.py)
    prior_missing: list[str] = state.get("missing_fields") or []
    missing: list[str] = []

    exercise_list = serialized.get("exercise", [])
    for ex in exercise_list if isinstance(exercise_list, list) else [exercise_list]:
        if isinstance(ex, dict):
            if not ex.get("exercise_type") and "exercise type" not in missing:
                missing.append("exercise type")
            # Don't re-ask for duration if we already asked — persist what we have
            if (
                not ex.get("duration_minutes")
                and "exercise duration" not in missing
                and "exercise duration" not in prior_missing
            ):
                missing.append("exercise duration")
            # Ask for body part if gym/weights and not already provided or asked
            is_gym = ex.get("exercise_type") in ("gym", "weights")
            if (
                is_gym
                and not ex.get("body_parts")
                and "body part" not in missing
                and "body part" not in prior_missing
            ):
                missing.append("body part")

    slp = serialized.get("sleep")
    if slp and isinstance(slp, dict):
        if (
            slp.get("bedtime_hour") is None
            and "bedtime" not in missing
            and "bedtime" not in prior_missing
        ):
            missing.append("bedtime")
        if (
            slp.get("wake_hour") is None
            and "wake up time" not in missing
            and "wake up time" not in prior_missing
        ):
            missing.append("wake up time")

    for practice_type in ['meditation', 'cleaning', 'sitting', 'group_meditation']:
        items = serialized.get(practice_type, [])
        for item in items:
            if isinstance(item, dict):
                if not item.get('duration_minutes'):
                    field = f'{practice_type.replace("_", " ")} duration'
                    if field not in missing and field not in prior_missing:
                        missing.append(field)
                if practice_type == 'sitting' and not item.get('took_from'):
                    if 'sitting trainer' not in missing and 'sitting trainer' not in prior_missing:
                        missing.append('sitting trainer')
                if practice_type == 'group_meditation' and not item.get('place'):
                    if 'group meditation place' not in missing and 'group meditation place' not in prior_missing:
                        missing.append('group meditation place')

    log.info("extraction_complete", fields_found=list(dumped.keys()), missing=missing)

    messages = [("user", state["raw_input"])]

    state_updates: dict[str, Any] = {
        "entities": serialized,
        "missing_fields": missing,
        "clarification_count": state.get("clarification_count", 0) + 1,
        "last_interaction_ts": now_ts,
    }

    if missing:
        if missing == ["body part"]:
            response_msg = (
                "Which body part(s) did you train? "
                "Options: Full body, Chest, Biceps, Triceps, Shoulders, Back, Abs, Lower body"
            )
        else:
            other = [m for m in missing if m != "body part"]
            parts = []
            if "sitting trainer" in other:
                parts.append("Who did you take the sitting from?")
                other.remove("sitting trainer")
            if "group meditation place" in other:
                parts.append("Where was the group meditation?")
                other.remove("group meditation place")
            if other:
                parts.append(f"Could you also specify the {', '.join(other)}?")
            if "body part" in missing:
                parts.append(
                    "Which body part(s) did you train? "
                    "Options: Full body, Chest, Biceps, Triceps, Shoulders, Back, Abs, Lower body"
                )
            response_msg = " ".join(parts)
            
        state_updates["response_message"] = response_msg
        messages.append(("assistant", response_msg))

    state_updates["chat_history"] = messages
    return state_updates
