from __future__ import annotations

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from life_os.agent.nodes import classifier, extractor, guard, persister, query
from life_os.agent.state import AgentState

log = structlog.get_logger(__name__)


def should_abort(state: AgentState) -> str:
    if state.get("abort"):
        return END
    return "extract"


def route_intent(state: AgentState) -> str:
    if state.get("intent") == "query":
        return "query"
    return "extract"


def check_missing_fields(state: AgentState) -> str:
    """If extraction resulted in missing fields, halt and ask user."""
    if state.get("missing_fields"):
        # Go straight to output/end, don't persist
        return "guard_output"
    return "persist"


# Define the graph
builder = StateGraph(AgentState)

# Add nodes
builder.add_node("guard_input", guard.run_input_guard)
builder.add_node("classify", classifier.run)
builder.add_node("query", query.run)
builder.add_node("extract", extractor.run)
builder.add_node("persist", persister.run)
builder.add_node("guard_output", guard.run_output_guard)

# Add edges
builder.add_edge(START, "guard_input")
builder.add_conditional_edges("guard_input", should_abort, {END: END, "extract": "classify"})
builder.add_conditional_edges("classify", route_intent, {"query": "query", "extract": "extract"})
builder.add_edge("query", "guard_output")
builder.add_conditional_edges(
    "extract", check_missing_fields, {"persist": "persist", "guard_output": "guard_output"}
)
builder.add_edge("persist", "guard_output")
builder.add_edge("guard_output", END)

memory = MemorySaver()
app = builder.compile(checkpointer=memory)
