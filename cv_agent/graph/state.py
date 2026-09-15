"""
cv_agent.graph.state — Shared agent state TypedDict.

AgentState is the single structure passed between all LangGraph nodes.
All keys are optional (total=False) so individual nodes can return only
the fields they mutate — LangGraph merges partial updates automatically.

Human-in-the-loop fields are reserved here so that later steps can
add interrupt nodes without restructuring the state schema.
"""

from __future__ import annotations

from typing import Any, Optional
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    """Shared state for the CV Engineering Agent graph."""

    # ── Session ──────────────────────────────────────────────────────────
    session_id: str
    """Unique identifier for this agent run."""

    status: str
    """Lifecycle status: initializing | ready | running | paused | done | error."""

    error: Optional[str]
    """Error message if status is 'error', otherwise None."""

    # ── Task context ──────────────────────────────────────────────────────
    task: Optional[str]
    """Natural-language description of the task being executed."""

    task_type: Optional[str]
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

    # ── Human-in-the-loop ────────────────────────────────────────────────
    pending_human_input: Optional[str]
    """Human-readable prompt describing what the graph is paused waiting
    for. Set by whichever node calls `interrupt()`; cleared on resume."""

    human_feedback: Optional[str]
    """Reserved, generic free-text human response slot. The structured
    workflow below (clarification/approval) uses its own typed fields
    instead of this one — see ADR-0003 — but it stays for a future node
    that only needs a single free-text answer."""

    # ── Requirements analysis + clarification (ADR-0003, ADR-0008) ─────────
    requirements_analysis: Optional[dict[str, Any]]
    """`dataclasses.asdict()` of the latest `RequirementsAnalysis` produced
    by `cv_agent.requirements.RequirementsAnalyzer`. Stored as a plain dict,
    not the dataclass itself, so orchestration state stays a serializable,
    checkpointer-safe structure independent of the reasoning layer's types
    (`[P§19]`/`[P§21]` layer separation) — see ADR-0003 §3."""

    clarification_answers: dict[str, str]
    """Human-supplied answers from the clarification interrupt, keyed by
    `RequirementField.name`. Empty until a human has actually answered —
    never pre-filled or guessed. Re-used as `assumptions` on the next
    `RequirementsAnalyzer.analyze()` call, exactly like any other caller-
    supplied assumption (ADR-0008 — the analyzer still never self-promotes
    a field on its own)."""

    # ── Approval + execution (ADR-0003, ADR-0009) ───────────────────────────
    pending_execution: Optional[dict[str, Any]]
    """What the caller is asking the graph to (attempt to) execute, if
    anything this run: `{"skill_id": str, "inputs": dict, "task": str |
    None}`. None means this run does not touch execution at all."""

    approval_decision: Optional[str]
    """"approved" | "rejected" | "not_required" | None (not yet decided).
    Set only by the approval-gate node from the value an `interrupt()` call
    actually receives on resume — never inferred, never defaulted to
    "approved". See ADR-0003 §5."""

    execution_result: Optional[dict[str, Any]]
    """`dataclasses.asdict()` of the `SkillExecutionResult` produced by
    `cv_agent.execution.SkillExecutor.execute()`, if the execute node ran.
    Same serialization rationale as `requirements_analysis`."""
