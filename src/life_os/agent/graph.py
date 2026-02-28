from __future__ import annotations

from typing import Any

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from openai import AsyncOpenAI

from life_os.agent.nodes import classifier, extractor, guard, persister, query
from life_os.agent.state import AgentState
from life_os.config.settings import settings

log = structlog.get_logger(__name__)


def should_abort(state: AgentState) -> str:
    if state.get("abort"):
        return END
    return "extract"


def route_intent(state: AgentState) -> str:
    intent = state.get("intent")
    if intent == "query":
        return "query"
    if intent == "other":
        return "chitchat"
    return "extract"


def check_missing_fields(state: AgentState) -> str:
    """If extraction resulted in missing fields, halt and ask user."""
    count = state.get("clarification_count", 0)
    if state.get("missing_fields") and count < settings.max_clarification_turns:
        # Go straight to output/end, don't persist
        return "guard_output"
    # Count exceeded: persist what we have
    return "persist"


_oai = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())


async def chitchat_node(state: AgentState) -> dict[str, Any]:
    """Acknowledge what the user said and gently offer to log or track."""
    text = state.get("raw_input", "")
    response = await _oai.chat.completions.create(
        model=settings.openai_model,
        temperature=0.5,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a friendly personal life assistant. The user sent a message that "
                    "doesn't clearly map to a data-logging or data-query action. "
                    "Briefly acknowledge what they said (1-2 sentences), then gently ask "
                    "if they'd like to log any part of it — e.g. mood, activity, tasks, or plans. "
                    "Be warm and concise. Do NOT repeat back lengthy quotes. Use plain text."
                ),
            },
            {"role": "user", "content": text},
        ],
    )
    reply = response.choices[0].message.content or "Got it! Anything you'd like me to log?"
    return {"response_message": reply}


# Define the graph
builder = StateGraph(AgentState)

# Add nodes
builder.add_node("guard_input", guard.run_input_guard)
builder.add_node("classify", classifier.run)
builder.add_node("query", query.run)
builder.add_node("extract", extractor.run)
builder.add_node("persist", persister.run)
builder.add_node("guard_output", guard.run_output_guard)

builder.add_node("chitchat", chitchat_node)

# Add edges
builder.add_edge(START, "guard_input")
builder.add_conditional_edges("guard_input", should_abort, {END: END, "extract": "classify"})
builder.add_conditional_edges(
    "classify", route_intent, {"query": "query", "extract": "extract", "chitchat": "chitchat"}
)
builder.add_edge("query", "guard_output")
builder.add_edge("chitchat", "guard_output")
builder.add_conditional_edges(
    "extract", check_missing_fields, {"persist": "persist", "guard_output": "guard_output"}
)
builder.add_edge("persist", "guard_output")
builder.add_edge("guard_output", END)

memory = MemorySaver()
app = builder.compile(checkpointer=memory)
