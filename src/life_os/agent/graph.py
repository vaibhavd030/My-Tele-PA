from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

import aiosqlite
import structlog
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from opentelemetry import trace

from life_os.agent.nodes import classifier, extractor, guard, persister, query
from life_os.agent.state import AgentState
from life_os.config.clients import calculate_cost, get_openai_client
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


def reset_node(state: AgentState) -> dict[str, Any]:
    """Clear entities for fresh messages to prevent bleed from past failure bounds."""
    if not state.get("missing_fields"):
        # For fresh conversations (not in clarification), reset everything.
        return {
            "entities": {},
            "missing_fields": [],
            "clarification_count": 0,
            "abort": False,
        }
    return {}


async def chitchat_node(state: AgentState) -> dict[str, Any]:
    """Acknowledge what the user said and gently offer to log or track."""
    text = state.get("raw_input", "")
    response = await get_openai_client().chat.completions.create(
        model=settings.openai_model,
        temperature=0.5,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a friendly personal life assistant. The user sent a message that "
                    "doesn't clearly map to a data-logging or data-query action. "
                    "Briefly acknowledge what they said (1-2 sentences), then gently ask "
                    "if they'd like to log any part of it — e.g. activity, tasks, or plans. "
                    "Be warm and concise. Do NOT repeat back lengthy quotes. Use plain text."
                ),
            },
            {"role": "user", "content": text},
        ],
    )
    reply = response.choices[0].message.content or "Got it! Anything you'd like me to log?"
    tokens, cost = calculate_cost(response.usage)
    return {"response_message": reply, "total_tokens": tokens, "total_cost_usd": cost}


tracer = trace.get_tracer("life_os")

def trace_node(func: Callable) -> Callable:
    @functools.wraps(func)
    async def wrapper(state: AgentState) -> dict[str, Any]:
        with tracer.start_as_current_span(func.__name__):
            return await func(state)
    return wrapper

def trace_sync_node(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(state: AgentState) -> dict[str, Any]:
        with tracer.start_as_current_span(func.__name__):
            return func(state)
    return wrapper

# Define the graph
builder = StateGraph(AgentState)

# Add nodes
builder.add_node("guard_input", trace_node(guard.run_input_guard))
builder.add_node("reset", trace_sync_node(reset_node))
builder.add_node("classify", trace_node(classifier.run))
builder.add_node("query", trace_node(query.run))
builder.add_node("extract", trace_node(extractor.run))
builder.add_node("persist", trace_node(persister.run))
builder.add_node("guard_output", trace_node(guard.run_output_guard))

builder.add_node("chitchat", trace_node(chitchat_node))

# Add edges
builder.add_edge(START, "reset")
builder.add_edge("reset", "guard_input")
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

_app = None

async def get_app():
    global _app
    if _app is None:
        db_path = settings.db_path.replace(".db", "_checkpoints.db")
        conn = await aiosqlite.connect(db_path)
        memory = AsyncSqliteSaver(conn)
        _app = builder.compile(checkpointer=memory)
    return _app
