"""
cv_agent.graph.state — Shared agent state TypedDict.

AgentState is the single structure passed between all LangGraph nodes.
All keys are optional (total=False) so individual nodes can return only
the fields they mutate — LangGraph merges partial updates automatically.

Human-in-the-loop fields are reserved here so that later steps can
add interrupt nodes without restructuring the state schema.
"""

from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    """Shared state for the CV Engineering Agent graph."""

    # ── Session ──────────────────────────────────────────────────────────
    session_id: str
    """Unique identifier for this agent run."""

    status: str
    """Lifecycle status: initializing | ready | running | paused | done | error."""

    error: str | None
    """Error message if status is 'error', otherwise None."""

    # ── Task context ──────────────────────────────────────────────────────
    task: str | None
    """Natural-language description of the task being executed."""

    task_type: str | None
    """Structured task type tag (matches capability applicable_task_types)."""

    # ── LLM context ───────────────────────────────────────────────────────
    provider: str
    """Active LLM provider name (e.g. 'mock', 'anthropic')."""

    model: str
    """Active model identifier."""

    # ── Capability context ────────────────────────────────────────────────
    selected_capabilities: list[str]
    """Capability IDs selected for the current task."""

    # ── Execution trace ───────────────────────────────────────────────────
    steps: list[dict[str, Any]]
    """Ordered log of node actions taken during this run."""

    # ── Human-in-the-loop (reserved for future steps) ─────────────────────
    pending_human_input: str | None
    """Prompt for the human reviewer when the graph is paused."""

    human_feedback: str | None
    """Response provided by the human reviewer after an interrupt."""
