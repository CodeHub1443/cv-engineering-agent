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
