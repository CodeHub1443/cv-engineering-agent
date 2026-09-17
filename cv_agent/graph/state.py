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

    # ── Execution inputs (ADR-0010 §12) ─────────────────────────────────
    execution_inputs: dict[str, Any]
    """Caller-supplied values for a candidate skill's declared
    `ExecutionBinding.input_schema` fields (ADR-0009 §11), keyed by
    `InputField.name` — a deliberately distinct namespace from
    `clarification_answers` above, which stays keyed by
    `RequirementField.name`. The two dicts are never merged or cross-read:
    an `InputField` name (e.g. "path") and a `RequirementField` name (e.g.
    "deployment_target") mean different things, and treating one as the
    other would be exactly the kind of silent inference `[P§35]` forbids.

    Set only via an explicit `CVAgent.start_workflow(execution_inputs=...)`
    argument (ADR-0010 §12) — empty (`{}`) by default, never inferred or
    pre-filled by any node. `plan_execution` reads this verbatim as
    `plan_execution()`'s `available_inputs` parameter; nothing else in the
    graph writes to it. V1 is pre-supply only: there is no interrupt that
    asks for a missing value mid-run (see `docs/state/OPEN_QUESTIONS.md`
    Q17, still open) — a caller who did not know the value before
    `start_workflow()` was called must retry with a new run once it does."""

    # ── Planning (ADR-0010) ──────────────────────────────────────────────
    planning_result: Optional[dict[str, Any]]
    """`dataclasses.asdict()` of the `PlanningResult` (`cv_agent.graph.
    planning`) produced by the most recent actual `plan_execution()` call
    this run — same serialization rationale as `requirements_analysis`/
    `execution_result` below. Shape: `{"status": PlanningStatus, "plan":
    dict | None, "candidate_skill_ids": tuple/list[str], "missing_inputs":
    tuple/list[str]}` (tuple on a fresh, non-checkpoint-restored run; may
    come back as a list after a checkpoint save/restore, same instability
    `requirements_analysis`'s own tuple fields already have — see
    `CVAgent._sync_memory_after_run()`); `plan`/`candidate_skill_ids`/
    `missing_inputs` are only meaningfully populated for the `PlanningStatus`
    value they document (see `cv_agent.graph.planning.PlanningResult`).

    `None` has two causes, exactly the same ambiguity `execution_result`
    already carries for `execute`: this run's `plan_execution` node has
    not run yet, OR it ran but *skipped* calling `plan_execution()` entirely
    because `pending_execution` was already caller-supplied (ADR-0010 §10)
    — a caller-supplied plan is never a `plan_execution()` decision, so
    there is no `PlanningResult` to report for it. `steps` still carries a
    `"caller_supplied_pending_execution_preserved"` entry for that case,
    same as before this field existed."""

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
