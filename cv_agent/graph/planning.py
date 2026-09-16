"""
cv_agent.graph.planning — ExecutionPlan contract + deterministic planner (ADR-0010).

`plan_execution()` implements ADR-0010 §3's V1 selection/input-completeness
rule as a plain, pure function — not yet wired into any graph. See ADR-0010
§9: a future `plan_execution` *node* (inserted into
`cv_agent.graph.workflow.build_requirements_workflow_graph()`'s existing
topology, between `analyze_requirements` and `approval_gate`) is a thin
wrapper around this function reading/writing `AgentState`, not built here.

Lives in `cv_agent.graph`, not `cv_agent.requirements`, because turning a
*candidate* (`cv_agent.requirements.models.SkillLink`) into a *decision*
(which one, with what inputs) is an orchestration responsibility, not a
reasoning one — see ADR-0010 §2 for why `RequirementsAnalyzer`, `TaskResolver`,
`SkillExecutor`, and `ExecutionRuntime` each explicitly do not own this.
`plan_execution()` itself calls none of them: it only reads
`RequirementsAnalysis.skill_links` (already computed) and
`ExecutionBindingRegistry.get_binding()` (inspect-only, the same read-only
call `cv_agent.graph.workflow`'s existing `approval_gate` node already makes
against `SkillExecutor.get_binding()` — this function depends on the
registry directly, not on `SkillExecutor`, so it cannot execute anything even
by accident).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from cv_agent.execution.binding import ExecutionBindingRegistry
from cv_agent.requirements.models import RequirementsAnalysis, SkillLink


@dataclass(frozen=True)
class ExecutionPlan:
    """
    The minimum information needed to turn one selected, executable
    `SkillLink` into a `SkillExecutionRequest`.

    Produced only by `plan_execution()` below, only when ADR-0010 §3's
    deterministic V1 rule finds exactly one executable candidate with every
    required input already known. Constructing one approves and executes
    nothing: it is a pure data record, read next by the *existing,
    unmodified* `approval_gate` node (ADR-0003), which remains the only path
    to `execute`/`SkillExecutor`.
    """

    skill_id: str
    """The selected SkillLink.skill_id — ADR-0010 §3's selection rule
    guarantees this is the one unambiguous executable candidate, never a
    silently-picked one among several."""

    task_component: str
    """The selected SkillLink.task_component — provenance only (which task
    component's resolution produced this candidate). Not read by
    approval_gate/execute; carried for audit/logging when this plan is
    materialized into AgentState["pending_execution"]. If the same skill_id
    was matched under more than one task component, this is whichever one
    appears first in `skill_links`' own deterministic order — a documented,
    arbitrary tie-break, not a ranking (see `plan_execution()`)."""

    inputs: dict[str, Any]
    """Same shape as SkillExecutionRequest.inputs — opaque to everything
    except the runtime the selected binding points at. A verbatim copy of
    whatever `plan_execution()` was given as `available_inputs`; never
    fabricated, never defaulted from `InputField.default` (see
    `plan_execution()`'s own docstring for why)."""

    source_task: str | None
    """The original natural-language request/task this plan serves —
    mirrors SkillExecutionRequest.task, for the same evidence-trail
    reason."""


PlanningStatus = Literal[
    "planned", "no_executable_candidate", "ambiguous_candidates", "missing_required_inputs"
]
"""
- planned: exactly one executable candidate, every required input known —
  `PlanningResult.plan` is set.
- no_executable_candidate: zero SkillLinks in `skill_links` are both
  `executable=True` and have a registered binding.
- ambiguous_candidates: more than one distinct skill_id qualifies as
  executable — ADR-0010 §3 step 4 forbids silently picking one.
  `PlanningResult.candidate_skill_ids` names them.
- missing_required_inputs: exactly one candidate, but its binding's
  `input_schema` declares a `required=True` field with no value in
  `available_inputs`. `PlanningResult.missing_inputs` names them.
"""


@dataclass(frozen=True)
class PlanningResult:
    """
    The outcome of one `plan_execution()` call — a normal, expected result
    for every branch, never an exception (ADR-0010 §7). A future
    `plan_execution` graph node branches on `.status`; only `"planned"`
    carries a `.plan` to write into `AgentState["pending_execution"]`.
    """

    status: PlanningStatus
    plan: ExecutionPlan | None = None
    """Set only when status == "planned"."""
    candidate_skill_ids: tuple[str, ...] = ()
    """Set only when status == "ambiguous_candidates" — every qualifying
    candidate's skill_id, sorted, for a future disambiguation UI/log line.
    Never used by this function to pick one."""
    missing_inputs: tuple[str, ...] = ()
    """Set only when status == "missing_required_inputs" — the names of
    every InputField.required field with no value in available_inputs,
    sorted."""


def plan_execution(
    analysis: RequirementsAnalysis,
    bindings: ExecutionBindingRegistry,
    *,
    available_inputs: dict[str, Any] | None = None,
) -> PlanningResult:
    """
    ADR-0010 §3's deterministic V1 planning rule. Pure and side-effect-free:
    reads `analysis.skill_links` and `bindings.get_binding()` (inspect-only),
    calls nothing else, executes nothing, approves nothing, invokes no LLM.

    Selection (never ranks, never scores, never silently picks one):
      1. Consider only `skill_links` entries that are `executable=True` AND
         have a binding actually registered in `bindings` — a `SkillLink`
         claiming `executable=True` against a *different* registry than the
         one passed here is treated as not-actually-verifiable-here, the
         same "don't trust an unconfirmed promise" posture
         `SkillExecutor.execute()` itself already takes for an unverified
         binding.
      2. Candidates are deduplicated by `skill_id`, not by `(task_component,
         skill_id)` — the same skill can legitimately appear under more than
         one matched task component (an existing, documented property of
         `skill_links`, unrelated to this function); that is one candidate,
         not several. The first occurrence in `skill_links`' own
         deterministic order supplies the plan's `task_component`.
      3. Zero qualifying candidates -> `"no_executable_candidate"`.
      4. Exactly one -> proceed to the input check below.
      5. More than one distinct skill_id -> `"ambiguous_candidates"`, listing
         every one; nothing is picked.

    Input completeness: reads the selected candidate's
    `ExecutionBinding.input_schema` (ADR-0009 §11) only to check whether
    every `required=True` field's *name* is a key in `available_inputs` —
    presence, not value validation (no type-checking, no `path`-XOR-`data`
    cross-field rule, no general validation engine: the runtime's own
    validation, e.g. `TrtPerfAnalysisRuntime._build_argv()`, remains
    authoritative, exactly as ADR-0009 §11 states). Any required field
    missing -> `"missing_required_inputs"`, listing every missing name; no
    plan is constructed. `InputField.default` is deliberately never applied
    here — this function only ever passes through what a caller explicitly
    supplied, never a value it invented on the field's behalf, keeping the
    "never fabricate" guarantee unconditional rather than schema-dependent.

    `ExecutionPlan.inputs` is a verbatim copy of `available_inputs`, not
    filtered down to only the binding's declared field names: a binding
    whose `input_schema` is still empty (`()`, the default — true of
    `trt-perf-analysis` today, ADR-0009 §11) reports no *required* input, but
    must not silently drop whatever the caller explicitly did supply.

    `bindings.get_binding()` is the only method this function calls on
    `ExecutionBindingRegistry` — it never calls `register_binding()`,
    never touches a runtime, never imports `SkillExecutor`.
    """
    known_inputs = available_inputs or {}

    candidates_by_skill_id: dict[str, SkillLink] = {}
    for link in analysis.skill_links:
        if not link.executable:
            continue
        if link.skill_id in candidates_by_skill_id:
            continue
        if bindings.get_binding(link.skill_id) is None:
            continue
        candidates_by_skill_id[link.skill_id] = link

    if not candidates_by_skill_id:
        return PlanningResult(status="no_executable_candidate")

    if len(candidates_by_skill_id) > 1:
        return PlanningResult(
            status="ambiguous_candidates",
            candidate_skill_ids=tuple(sorted(candidates_by_skill_id)),
        )

    (selected,) = candidates_by_skill_id.values()
    binding = bindings.get_binding(selected.skill_id)
    assert binding is not None  # guaranteed by the filter above

    missing = sorted(
        field.name
        for field in binding.input_schema
        if field.required and field.name not in known_inputs
    )
    if missing:
        return PlanningResult(status="missing_required_inputs", missing_inputs=tuple(missing))

    plan = ExecutionPlan(
        skill_id=selected.skill_id,
        task_component=selected.task_component,
        inputs=dict(known_inputs),
        source_task=analysis.original_request,
    )
    return PlanningResult(status="planned", plan=plan)
