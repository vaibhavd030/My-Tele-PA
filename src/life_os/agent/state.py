"""Agent state for the LangGraph workflow."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict
import operator

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


def add_metadata(left: int | float | None, right: int | float | None) -> int | float:
    return (left or 0) + (right or 0)


class AgentState(TypedDict, total=False):
    """State passed between nodes in the LangGraph workflow.

    Attributes:
        chat_history: List of past interactions (input/output) appended each turn.
        user_id: Unique identifier for the user (e.g., Telegram chat ID).
        raw_input: The raw message text from the user.
        entities: Dictionary of extracted wellness entities.
        missing_fields: List of fields that need clarification.
        clarification_count: Number of times the agent has asked for clarification.
        abort: Flag to stop processing and return early (e.g., on safety check fail).
        response_message: The final text response to send back to the user.
        structured_records: The validated data records ready to be written to storage.
    """

    chat_history: Annotated[list[AnyMessage], add_messages]
    user_id: str
    raw_input: str
    entities: Annotated[dict[str, Any], operator.ior]
    missing_fields: list[str]
    clarification_count: int
    intent: str | None
    abort: bool
    input_modality: str | None
    voice_file_id: str | None
    response_message: str | None
    structured_records: list[dict[str, Any]]
    last_interaction_ts: float
    total_tokens: Annotated[int, add_metadata]
    total_cost_usd: Annotated[float, add_metadata]
