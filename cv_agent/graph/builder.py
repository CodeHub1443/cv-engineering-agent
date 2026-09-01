"""
cv_agent.graph.builder — LangGraph graph construction.

build_graph() returns a compiled, checkpointed StateGraph ready for
synchronous or async invocation.

Step 1 topology (minimal):
    START → initialize → END

The MemorySaver checkpointer makes every run resumable by thread_id, which
is the prerequisite for adding human-interrupt nodes in later steps.
Later steps will insert plan / act / reflect / human_review nodes between
initialize and END without restructuring the existing node contracts.
"""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from cv_agent.graph.state import AgentState
# ── Node implementations ──────────────────────────────────────────────────────


def _node_initialize(state: AgentState) -> dict[str, Any]:
    """
    Initialize node — always the first node to run.

    Responsibilities:
        - Assign a session ID if one was not provided.
        - Set status to 'ready'.
        - Append an entry to the execution trace.

    Returns a partial state update; LangGraph merges it into the full state.
    """
    steps: list[dict[str, Any]] = list(state.get("steps", []))
    steps.append(
        {
            "node": "initialize",
            "action": "session_started",
            "session_id": state.get("session_id") or "pending",
        }
    )
    return {
        "session_id": state.get("session_id") or str(uuid.uuid4()),
        "status": "ready",
        "error": None,
        "steps": steps,
    }


# ── Graph construction ────────────────────────────────────────────────────────


def build_graph(checkpointer: Any = None) -> Any:
    """
    Build and compile the CV Agent LangGraph StateGraph.

    Args:
        checkpointer: LangGraph checkpointer to use for state persistence.
                      Defaults to MemorySaver (in-process, no external deps).
                      Pass None explicitly to use the default.

    Returns:
        A compiled LangGraph graph (CompiledStateGraph) ready to invoke.

    Notes:
        The returned graph requires ``config={"configurable": {"thread_id": ...}}``
        on every invoke/stream call because MemorySaver is thread-keyed.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    builder: StateGraph = StateGraph(AgentState)

    # Nodes
    builder.add_node("initialize", _node_initialize)

    # Edges
    builder.add_edge(START, "initialize")
    builder.add_edge("initialize", END)

    return builder.compile(checkpointer=checkpointer)
