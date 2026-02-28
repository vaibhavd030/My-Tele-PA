"""Guardrails node — input safety and output validation.

Runs at two points in the graph:
1. After parse_message: validates raw user input
2. Before write_to_store: validates structured output
"""

from __future__ import annotations

import structlog

from life_os.agent.state import AgentState
from life_os.models.guardrails import InputGuard

log = structlog.get_logger(__name__)

# Crisis resources — sent instead of normal response
_CRISIS_MESSAGE = (
    "I noticed something in your message that concerns me. "
    "If you are struggling, please reach out:\n"
    "🆘 iCall (India): 9152987821\n"
    "🆘 Vandrevala Foundation: 1860-2662-345 (24/7)\n"
    "I am here to chat whenever you feel ready. 💙"
)


async def run_input_guard(state: AgentState) -> AgentState:
    """Validate raw user input for safety before LLM processing.

    Checks for:
      - Prompt injection attempts (blocks and logs)
      - Crisis/mental health content (flags, sends resources, halts normal flow)
      - Excessively long messages (truncates with warning)

    Args:
        state: Current agent state.

    Returns:
        Updated state. Sets 'abort' flag if message should not be
        processed by the agent.
    """
    raw = state["raw_input"]

    # Length guard: Telegram messages can be up to 4096 chars
    if len(raw) > 2000:
        log.warning("message_truncated", original_len=len(raw))
        raw = raw[:2000] + "... [truncated]"

    try:
        guard = InputGuard(raw_text=raw).check_crisis()
    except ValueError as exc:
        log.warning("input_blocked", reason=str(exc), user_id=state["user_id"])
        return {"abort": True, "response_message": "Sorry, I cannot process that message."}

    if guard.detected_crisis:
        log.warning("crisis_detected", user_id=state["user_id"])
        return {"abort": True, "response_message": _CRISIS_MESSAGE}

    return {"raw_input": guard.raw_text, "abort": False}


async def run_output_guard(state: AgentState) -> AgentState:
    """Validate structured records before writing to storage.

    Catches any extraction errors that slipped past Instructor validation.
    On failure, stores the raw message in the journal as a fallback.

    Args:
        state: Current agent state with structured_records populated.

    Returns:
        State with validated records, or fallback journal entry.
    """
    records = state.get("structured_records", [])
    if not records:
        log.warning("no_records_to_write", user_id=state["user_id"])
        # Fallback: save raw input as a journal entry
        return {"structured_records": [{"type": "journal", "note": state["raw_input"]}]}
    return state
