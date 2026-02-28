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

    existing = state.get("entities", {})
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
                # Merge single-item lists (e.g. clarifying one exercise session)
                if len(ex_val) == 1 and len(new_val) == 1 and hasattr(new_val[0], "model_dump"):
                    old_dict = (
                        ex_val[0]
                        if isinstance(ex_val[0], dict)
                        else ex_val[0].model_dump(exclude_unset=True, exclude_none=True)
                    )
                    new_dict = new_val[0].model_dump(exclude_unset=True, exclude_none=True)
                    merged[k] = [{**old_dict, **new_dict}]
                else:
                    # Combine both lists; serialize new items to dicts
                    serialized_new = [
                        (
                            v.model_dump(exclude_unset=True, exclude_none=True)
                            if hasattr(v, "model_dump")
                            else v
                        )
                        for v in new_val
                    ]
                    existing_list = ex_val if isinstance(ex_val, list) else [ex_val]
                    merged[k] = existing_list + serialized_new
            elif hasattr(new_val, "model_dump") and isinstance(ex_val, dict):
                merged[k] = {**ex_val, **new_val.model_dump(exclude_unset=True, exclude_none=True)}
            elif hasattr(new_val, "model_dump") and hasattr(ex_val, "model_dump"):
                old_dict = ex_val.model_dump(exclude_unset=True, exclude_none=True)
                new_dict = new_val.model_dump(exclude_unset=True, exclude_none=True)
                merged[k] = {**old_dict, **new_dict}
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
            serialized[k] = v.model_dump(exclude_none=True)
        elif isinstance(v, list):
            serialized[k] = [
                item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else item
                for item in v
            ]
        else:
            serialized[k] = v

    # ── Missing-field checks (work on serialized plain dicts) ─────────────
    missing: list[str] = []

    exercise_list = serialized.get("exercise", [])
    for ex in exercise_list if isinstance(exercise_list, list) else [exercise_list]:
        if isinstance(ex, dict):
            if not ex.get("exercise_type") and "exercise type" not in missing:
                missing.append("exercise type")
            if not ex.get("duration_minutes") and "exercise duration" not in missing:
                missing.append("exercise duration")

    slp = serialized.get("sleep")
    if slp and isinstance(slp, dict):
        if slp.get("bedtime_hour") is None and "bedtime" not in missing:
            missing.append("bedtime")
        if slp.get("wake_hour") is None and "wake up time" not in missing:
            missing.append("wake up time")
        if not slp.get("quality") and "sleep quality" not in missing:
            missing.append("sleep quality")

    log.info("extraction_complete", fields_found=list(new_data.keys()), missing=missing)

    state_updates: dict[str, Any] = {
        "entities": serialized,
        "chat_history": [("user", state["raw_input"])],
        "missing_fields": missing,
        "clarification_count": state.get("clarification_count", 0) + 1,
    }

    if missing:
        missing_str = ", ".join(missing)
        state_updates["response_message"] = f"Got it! Could you also specify the {missing_str}?"

    return state_updates
