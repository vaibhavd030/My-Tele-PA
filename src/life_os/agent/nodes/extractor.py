"""Entity extraction node — the core intelligence of the agent.

Uses Instructor to enforce GPT-4o returns a validated ExtractedData Pydantic model.
Handles partial data gracefully for the clarification loop downstream.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import instructor
import structlog
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from life_os.agent.state import AgentState
from life_os.config.settings import settings
from life_os.models.wellness import ExtractedData

log = structlog.get_logger(__name__)

# Patch the async OpenAI client with Instructor
_client = instructor.from_openai(
    AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value()), mode=instructor.Mode.JSON
)

_SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "extract.txt").read_text()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def _call_llm(text: str, today: date, chat_history: str = "") -> ExtractedData:
    """Call GPT-4o with Instructor to extract structured wellness data.

    Args:
        text: The raw user message to extract from.
        today: Current date for resolving relative references like 'today'.
        chat_history: String representation of recent conversation turns to prevent duplicates.

    Returns:
        ExtractedData with all detected wellness fields populated.

    Raises:
        instructor.exceptions.InstructorRetryException: After 3 failed
            validation attempts.
    """
    return await _client.chat.completions.create(
        model="gpt-4o-mini",  # gpt-4o-mini is 10x cheaper, sufficient here
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

    # Build a simple string of the last few messages for the LLM
    history = state.get("chat_history", [])
    history_str = "\n".join([f"{msg.type}: {msg.content}" for msg in history[-5:]])

    extracted = await _call_llm(
        text=state["raw_input"], today=date.today(), chat_history=history_str
    )

    # If we are currently clarifying, merge with existing state. 
    # If the missing_fields list is empty, this is a fresh conversational turn; do NOT merge.
    if state.get("missing_fields"):
        existing = state.get("entities", {})
    else:
        existing = {}

    new_data = {}
    for k in type(extracted).model_fields:
        val = getattr(extracted, k)
        if val is not None and val != []:
            new_data[k] = val

    # ── Merge new data with existing entities ─────────────────────────────
    merged: dict[str, Any] = {}
    for k in type(extracted).model_fields:
        ex_val = existing.get(k)
        new_val = new_data.get(k)

        if ex_val and new_val:
            if isinstance(ex_val, list) and isinstance(new_val, list):
                existing_list = [
                    (v if isinstance(v, dict) else v.model_dump(exclude_unset=True, exclude_none=True))
                    for v in ex_val
                ]
                new_list = [
                    (v.model_dump(exclude_unset=True, exclude_none=True) if hasattr(v, "model_dump") else v)
                    for v in new_val
                ]

                # Smart merge: try to update existing items rather than just concatenating
                for new_item in new_list:
                    match_idx = -1
                    # Match by type if available
                    if new_item.get("exercise_type"):
                        for i, old_item in enumerate(existing_list):
                            if old_item.get("exercise_type") == new_item["exercise_type"]:
                                match_idx = i
                                break
                    # Or find an item missing a value that the new item provides
                    if match_idx == -1:
                        for key, val in new_item.items():
                            if val is not None:
                                for i, old_item in enumerate(existing_list):
                                    if old_item.get(key) is None:
                                        match_idx = i
                                        break
                            if match_idx != -1:
                                break
                    
                    if match_idx != -1:
                        existing_list[match_idx] = {**existing_list[match_idx], **new_item}
                    else:
                        existing_list.append(new_item)
                
                merged[k] = existing_list
            elif hasattr(new_val, "model_dump") and isinstance(ex_val, dict):
                merged[k] = {**ex_val, **new_val.model_dump(exclude_unset=True, exclude_none=True)}
            elif hasattr(new_val, "model_dump") and hasattr(ex_val, "model_dump"):
                old_dict = ex_val.model_dump(exclude_unset=True, exclude_none=True)
                new_dict = new_val.model_dump(exclude_unset=True, exclude_none=True)
                merged[k] = {**old_dict, **new_dict}
            elif isinstance(ex_val, str) and isinstance(new_val, str):
                if new_val in ex_val:
                    merged[k] = ex_val
                elif len(new_val) <= 40 or len(new_val) < len(ex_val) * 0.5:
                    merged[k] = ex_val  # don't overwrite long notes with short clarification notes
                else:
                    merged[k] = ex_val + "\n\n" + new_val
            else:
                merged[k] = new_val
        elif new_val is not None:
            merged[k] = new_val
        elif ex_val is not None:
            merged[k] = ex_val

    # ── Serialize ALL Pydantic objects → plain dicts for msgpack ──────────
    # LangGraph's MemorySaver uses msgpack which cannot handle Pydantic models.
    serialized: dict[str, Any] = {}
    for k, v in merged.items():
        if hasattr(v, "model_dump"):
            serialized[k] = v.model_dump(mode="json", exclude_none=True)
        elif isinstance(v, list):
            serialized[k] = [
                (
                    item.model_dump(mode="json", exclude_none=True)
                    if hasattr(item, "model_dump")
                    else item
                )
                for item in v
            ]
        else:
            serialized[k] = v

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
        if (
            not slp.get("quality")
            and "sleep quality" not in missing
            and "sleep quality" not in prior_missing
        ):
            missing.append("sleep quality")

    log.info("extraction_complete", fields_found=list(new_data.keys()), missing=missing)

    messages = [("user", state["raw_input"])]

    state_updates: dict[str, Any] = {
        "entities": serialized,
        "missing_fields": missing,
        "clarification_count": state.get("clarification_count", 0) + 1,
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
