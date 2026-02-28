"""Entity extraction node — the core intelligence of the agent.

Uses Instructor to enforce GPT-4o returns a validated ExtractedData Pydantic model.
Handles partial data gracefully for the clarification loop downstream.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

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
                    _SYSTEM_PROMPT.format(today=today.isoformat()) + 
                    "\n\nRecent Chat History (Use this to avoid extracting duplicate information "
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
        text=state["raw_input"],
        today=date.today(),
        chat_history=history_str
    )

    existing = state.get("entities", {})
    new_data = {}
    for k in type(extracted).model_fields:
        val = getattr(extracted, k)
        if val is not None and val != []:
            new_data[k] = val

    merged = {}
    for k in type(extracted).model_fields:
        ex_val = existing.get(k)
        new_val = new_data.get(k)
        
        if ex_val and new_val:
            if isinstance(ex_val, list) and isinstance(new_val, list):
                # If clarifying a single item in a list (like 1 exercise), merge them
                if len(ex_val) == 1 and len(new_val) == 1 and hasattr(ex_val[0], "model_dump"):
                    old_dict = ex_val[0].model_dump(exclude_unset=True, exclude_none=True)
                    new_dict = new_val[0].model_dump(exclude_unset=True, exclude_none=True)
                    merged[k] = [type(ex_val[0])(**{**old_dict, **new_dict})]
                else:
                    merged[k] = ex_val + new_val
            elif hasattr(ex_val, "model_dump") and hasattr(new_val, "model_dump"):
                old_dict = ex_val.model_dump(exclude_unset=True, exclude_none=True)
                new_dict = new_val.model_dump(exclude_unset=True, exclude_none=True)
                merged[k] = type(ex_val)(**{**old_dict, **new_dict})
            else:
                merged[k] = new_val
        elif new_val:
            merged[k] = new_val
        elif ex_val:
            merged[k] = ex_val
    
    # Simple required-field check
    missing = []
    
    if "exercise" in merged and merged["exercise"]:
        for ex in merged["exercise"]:
            if getattr(ex, "exercise_type", None) is None and "exercise type" not in missing:
                missing.append("exercise type")
            if getattr(ex, "duration_minutes", None) is None and "exercise duration" not in missing:
                missing.append("exercise duration")

    if "sleep" in merged and merged["sleep"]:
        slp = merged["sleep"]
        if getattr(slp, "bedtime_hour", None) is None and "bedtime" not in missing:
            missing.append("bedtime")
        if getattr(slp, "wake_hour", None) is None and "wake up time" not in missing:
            missing.append("wake up time")
        if getattr(slp, "quality", None) is None and "sleep quality" not in missing:
            missing.append("sleep quality")

    log.info("extraction_complete", fields_found=list(new_data.keys()), missing=missing)
    
    state_updates = {
        "entities": merged, 
        "chat_history": [("user", state["raw_input"])],
        "missing_fields": missing
    }
    
    if missing:
        missing_str = ", ".join(missing)
        state_updates["response_message"] = f"Got it! Could you also specify the {missing_str}?"
        
    return state_updates
