"""
cv_agent.graph.planning — ExecutionPlan contract (ADR-0010).

Types only — no selection logic, no node, no graph wiring. See ADR-0010 §9:
this module exists so a future `plan_execution` graph node (inserted into
`cv_agent.graph.workflow.build_requirements_workflow_graph()`'s existing
topology, between `analyze_requirements` and `approval_gate`) has a stable,
already-agreed target type to build against — not implemented here.

Lives in `cv_agent.graph`, not `cv_agent.requirements`, because turning a
*candidate* (`cv_agent.requirements.models.SkillLink`) into a *decision*
(which one, with what inputs) is an orchestration responsibility, not a
reasoning one — see ADR-0010 §2 for why `RequirementsAnalyzer`, `TaskResolver`,
`SkillExecutor`, and `ExecutionRuntime` each explicitly do not own this.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionPlan:
    """
    The minimum information needed to turn one selected, executable
    `SkillLink` into a `SkillExecutionRequest`.

    Produced (by a future `plan_execution` node, not yet implemented — see
    ADR-0010 §9) only when ADR-0010 §3's deterministic V1 rule finds exactly
    one executable candidate with every required input already known.
    Constructing one approves and executes nothing: it is a pure data
    record, read next by the *existing, unmodified* `approval_gate` node
    (ADR-0003), which remains the only path to `execute`/`SkillExecutor`.
    """

    skill_id: str
    """The selected SkillLink.skill_id — ADR-0010 §3's selection rule
    guarantees this is the one unambiguous executable candidate, never a
    silently-picked one among several."""

    task_component: str
    """The selected SkillLink.task_component — provenance only (which task
    component's resolution produced this candidate). Not read by
    approval_gate/execute; carried for audit/logging when this plan is
    materialized into AgentState["pending_execution"]."""

    inputs: dict[str, Any]
    """Same shape as SkillExecutionRequest.inputs — opaque to everything
    except the runtime the selected binding points at. Built only from
    caller-supplied values, checked against the binding's declared
    InputField.required set (ADR-0009 §11); never fabricated."""

    source_task: str | None
    """The original natural-language request/task this plan serves —
    mirrors SkillExecutionRequest.task, for the same evidence-trail
    reason."""
