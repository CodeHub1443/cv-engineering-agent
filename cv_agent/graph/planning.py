"""
cv_agent.graph.planning — ExecutionPlan contract + deterministic planner (ADR-0010).

`plan_execution()` implements ADR-0010 §3's V1 selection/input-completeness
rule as a plain, pure function. See ADR-0010 §10: the `plan_execution` graph
node (inserted into `cv_agent.graph.workflow.build_requirements_workflow_graph()`'s
topology, between `analyze_requirements`/`clarify` and `approval_gate`) is a
thin wrapper around this function that reads/writes `AgentState` — this
module itself still knows nothing about `AgentState`, LangGraph, or
`approval_gate`/`execute`; the node lives in `cv_agent.graph.workflow`, not
here.

Lives in `cv_agent.graph`, not `cv_agent.requirements`, because turning a
*candidate* (`cv_agent.requirements.models.SkillLink`) into a *decision*
(which one, with what inputs) is an orchestration responsibility, not a
reasoning one — see ADR-0010 §2 for why `RequirementsAnalyzer`, `TaskResolver`,
`SkillExecutor`, and `ExecutionRuntime` each explicitly do not own this.
`plan_execution()` itself calls none of them: it only reads
`RequirementsAnalysis.skill_links` (already computed) and
`ExecutionBindingRegistry.get_binding()` (inspect-only — this function
depends on the registry directly, not on `SkillExecutor`, so it cannot
execute anything even by accident).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from cv_agent.execution.binding import ExecutionBindingRegistry, InputField, RequiredFieldGroup
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
    "planned",
    "no_executable_candidate",
    "ambiguous_candidates",
    "missing_required_inputs",
    "conflicting_inputs",
]
"""
- planned: exactly one executable candidate, every required input known,
  and every `"exactly_one"` group has exactly one member present —
  `PlanningResult.plan` is set.
- no_executable_candidate: zero SkillLinks in `skill_links` are both
  `executable=True` and have a registered binding.
- ambiguous_candidates: more than one distinct skill_id qualifies as
  executable — ADR-0010 §3 step 4 forbids silently picking one.
  `PlanningResult.candidate_skill_ids`/`candidate_descriptions` name them.
  Resolvable within the same run via a caller-supplied `selected_skill_id`
  (ADR-0010 §16, resolving Q18) naming one of them.
- missing_required_inputs: exactly one candidate, but its binding's
  `input_schema` declares a `required=True` field with no value in
  `available_inputs`, or an `"exactly_one"` `RequiredFieldGroup` has ZERO
  members present. `PlanningResult.missing_inputs` names them.
- conflicting_inputs: exactly one candidate, but an `"exactly_one"`
  `RequiredFieldGroup` has TWO OR MORE members present in
  `available_inputs` — a genuine XOR violation, caught here rather than
  left to the runtime (ADR-0009 §12/§13, ADR-0010 §15). Takes priority
  over `missing_required_inputs` when both would otherwise apply, since a
  contradictory answer needs correcting regardless of what else is
  missing. `PlanningResult.conflicting_inputs` names the offending
  members that were actually supplied together."""


@dataclass(frozen=True)
class PlanningResult:
    """
    The outcome of one `plan_execution()` call — a normal, expected result
    for every branch, never an exception (ADR-0010 §7). The `plan_execution`
    graph node (ADR-0010 §10, `cv_agent.graph.workflow`) branches on
    `.status`; only `"planned"` carries a `.plan` to write into
    `AgentState["pending_execution"]`. The full result is also mirrored into
    `AgentState["planning_result"]` (ADR-0010 §11) for callers that need more
    than the plan/no-plan distinction `pending_execution` alone carries.
    """

    status: PlanningStatus
    plan: ExecutionPlan | None = None
    """Set only when status == "planned"."""
    candidate_skill_ids: tuple[str, ...] = ()
    """Set only when status == "ambiguous_candidates" — every qualifying
    candidate's skill_id, sorted. Never used by this function to pick one."""
    candidate_descriptions: tuple[str, ...] = ()
    """Companion to `candidate_skill_ids` (ADR-0010 §16, resolving Q18) —
    same order, same length, each entry the matching candidate's
    `ExecutionBinding.description` (never a live re-lookup by a caller;
    this snapshot is what the `choose_candidate` interrupt node presents to
    a human, sourced once, here, at plan time). `ExecutionBinding.
    description` — not `Skill.description` from `SKILL.md` frontmatter —
    is deliberately the source: `plan_execution()`'s only dependencies are
    `RequirementsAnalysis` and `ExecutionBindingRegistry` (see this
    module's own docstring); reading `Skill` would mean depending on
    `SkillInventory` too, a boundary this function has never crossed."""
    missing_inputs: tuple[str, ...] = ()
    """Set only when status == "missing_required_inputs" — the names of
    every InputField.required field with no value in available_inputs,
    plus every member name of any `RequiredFieldGroup` with zero members
    present, sorted."""
    conflicting_inputs: tuple[str, ...] = ()
    """Set only when status == "conflicting_inputs" (ADR-0010 §15,
    resolving the review finding that "at least one" alone did not satisfy
    the decided oneOf/XOR semantics) — the names of every field that was
    actually supplied together in `available_inputs` for a
    `RequiredFieldGroup` whose `kind == "exactly_one"` constraint that
    combination violates, sorted. Never populated alongside
    `missing_inputs` in the same result — `conflicting_inputs` takes
    priority (see `plan_execution()`)."""
    candidate_binding_ids: tuple[str, ...] = ()
    """Companion to `candidate_skill_ids`/`candidate_descriptions` (ADR-0010
    §16.3, audit finding D1) — same order, same length, each entry the
    matching candidate's `ExecutionBinding.binding_id` at plan time. This is
    what pins a human's choice to the *exact binding they were shown*, not
    merely a `skill_id`: the same skill_id can be re-registered under a new
    binding_id (different runtime, different behavior) during the pause,
    and only a binding_id recorded at ask time can detect that. Populated
    only for "ambiguous_candidates"."""
    selected_skill_id: str | None = None
    """Set whenever exactly one candidate was selected — status == "planned",
    "missing_required_inputs", OR "conflicting_inputs" (never for
    "no_executable_candidate"/"ambiguous_candidates", where there is no
    single selected candidate). ADR-0010 §13: this is what lets a caller
    (the `plan_execution` graph node's same-session missing-input recovery)
    record *which* candidate a human is being asked about, and later verify
    — from checkpointed state, not a fresh registry lookup — that a retry
    still targets the same one. Redundant with `plan.skill_id` when status
    == "planned"; the only place that carries this identity for
    "missing_required_inputs"/"conflicting_inputs" at all."""
    selected_binding_id: str | None = None
    """Companion to `selected_skill_id` — the specific `ExecutionBinding.
    binding_id` selected, not just the skill_id. Set together with
    `selected_skill_id`, same statuses. A binding can in principle be
    re-registered under the same skill_id with a different binding_id;
    carrying both, not skill_id alone, is what makes that detectable
    (ADR-0010 §13)."""
    selected_description: str | None = None
    """Companion to `selected_binding_id` (ADR-0010 section 17, issue #43): the
    selected candidate's `ExecutionBinding.description` at plan time - the
    snapshot `provide_execution_inputs` records as `expected_description` so a
    description-only change during that pause fails closed, exactly as
    `choose_candidate` already pins it (section 16.3). Set together with
    `selected_binding_id`, same statuses."""
    selected_input_schema: tuple[InputField, ...] | None = None
    """A verbatim snapshot of the selected candidate's `ExecutionBinding.
    input_schema` at the moment of selection — set together with
    `selected_skill_id`/`selected_binding_id`. ADR-0010 §13: `binding_id`
    string equality alone does not prove the *contract* is unchanged (the
    same binding_id could be re-registered with a renamed field, a changed
    description/default, or a flipped `required` flag). This snapshot is
    what a same-session recovery round compares against, structurally,
    before ever trusting a human-supplied value or producing a plan from
    it — never a fresh, live registry lookup at comparison time."""
    selected_input_field_groups: tuple[RequiredFieldGroup, ...] | None = None
    """Companion snapshot to `selected_input_schema` — the selected
    candidate's `ExecutionBinding.input_field_groups` (ADR-0009 §12) at the
    moment of selection, same two statuses, same "structural comparison,
    never a live lookup" recovery guarantee (ADR-0010 §14). A binding whose
    individual fields are unchanged but whose group constraints were
    altered underneath a paused recovery round must still be detected as
    changed — comparing `selected_input_schema` alone would miss that."""


def plan_execution(
    analysis: RequirementsAnalysis,
    bindings: ExecutionBindingRegistry,
    *,
    available_inputs: dict[str, Any] | None = None,
    selected_skill_id: str | None = None,
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
      5. More than one distinct skill_id: if `selected_skill_id` names one
         of them, that one is selected and this function proceeds exactly
         as if it had been the only candidate (ADR-0010 §16, resolving
         Q18) — this is the *only* way more than one candidate is ever
         resolved to one; nothing is picked when `selected_skill_id` is
         `None` or does not name a current candidate (a stale/invalid
         choice is silently ignored here, not trusted — the caller, e.g.
         the `choose_candidate` graph node's retry, is responsible for
         detecting and reporting that as a mismatch, since only it knows
         whether a choice was actually offered before). Otherwise ->
         `"ambiguous_candidates"`, listing every one; nothing is picked.

    Input completeness: reads the selected candidate's
    `ExecutionBinding.input_schema` (ADR-0009 §11) to check whether every
    `required=True` field's *name* is a key in `available_inputs`, AND
    reads `ExecutionBinding.input_field_groups` (ADR-0009 §12, resolving
    Q20) to check whether every `"exactly_one"` group has EXACTLY one
    member name present — true oneOf/XOR semantics (ADR-0010 §15,
    correcting an earlier "at least one" version of this check that did
    not fully satisfy the decision's own name). Zero members present for a
    group, or a required field missing, -> `"missing_required_inputs"`,
    listing every missing individual field name and, for each unsatisfied
    group, every one of its member names (so a caller sees "supply one of
    path/data", not a composite string requiring a new shape to parse).
    TWO OR MORE members present for a group -> `"conflicting_inputs"`
    (checked and returned before `"missing_required_inputs"` even if both
    would otherwise apply on different fields/groups of the same
    candidate), listing exactly the member names that were actually
    supplied together in `PlanningResult.conflicting_inputs` — a caller
    knows precisely what to remove, not merely that "something is wrong."
    Neither check is value/type validation (no rejection based on a
    field's *content*, only its *presence* and *count* — the runtime's own
    validation, e.g. `TrtPerfAnalysisRuntime._build_argv()`, remains the
    authoritative final check, exactly as ADR-0009 §11/§12/§13 state). No
    plan is constructed for either case. `InputField.default` is
    deliberately never applied here — this function only ever passes
    through what a caller explicitly supplied, never a value it invented
    on the field's behalf, keeping the
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

    if len(candidates_by_skill_id) == 1:
        (selected,) = candidates_by_skill_id.values()
    elif selected_skill_id is not None and selected_skill_id in candidates_by_skill_id:
        # ADR-0010 §16 (Q18): a validated disambiguation choice resolves
        # ambiguity exactly like there having been only one candidate all
        # along — everything below (input completeness, plan construction)
        # is identical either way, never duplicated for this path.
        selected = candidates_by_skill_id[selected_skill_id]
    else:
        candidate_ids = tuple(sorted(candidates_by_skill_id))
        candidate_descriptions = []
        candidate_binding_ids = []
        for skill_id in candidate_ids:
            candidate_binding = bindings.get_binding(skill_id)
            assert candidate_binding is not None  # guaranteed by the filter above
            candidate_descriptions.append(candidate_binding.description)
            candidate_binding_ids.append(candidate_binding.binding_id)
        return PlanningResult(
            status="ambiguous_candidates",
            candidate_skill_ids=candidate_ids,
            candidate_descriptions=tuple(candidate_descriptions),
            candidate_binding_ids=tuple(candidate_binding_ids),
        )

    binding = bindings.get_binding(selected.skill_id)
    assert binding is not None  # guaranteed by the filter above

    missing_individual = {
        field.name
        for field in binding.input_schema
        if field.required and field.name not in known_inputs
    }
    missing_group_members: set[str] = set()
    conflicting_group_members: set[str] = set()
    for group in binding.input_field_groups:
        present = [name for name in group.field_names if name in known_inputs]
        if not present:
            missing_group_members.update(group.field_names)
        elif len(present) > 1:
            # True XOR: more than one member of an "exactly_one" group was
            # supplied together — a contradictory answer, not merely an
            # incomplete one. Checked and reported ahead of
            # "missing_required_inputs" below (ADR-0010 §15).
            conflicting_group_members.update(present)
        # len(present) == 1: this group is satisfied, nothing to report.

    if conflicting_group_members:
        return PlanningResult(
            status="conflicting_inputs",
            conflicting_inputs=tuple(sorted(conflicting_group_members)),
            selected_skill_id=selected.skill_id,
            selected_binding_id=binding.binding_id,
            selected_description=binding.description,
            selected_input_schema=binding.input_schema,
            selected_input_field_groups=binding.input_field_groups,
        )

    missing = sorted(missing_individual | missing_group_members)
    if missing:
        return PlanningResult(
            status="missing_required_inputs",
            missing_inputs=tuple(missing),
            selected_skill_id=selected.skill_id,
            selected_binding_id=binding.binding_id,
            selected_description=binding.description,
            selected_input_schema=binding.input_schema,
            selected_input_field_groups=binding.input_field_groups,
        )

    plan = ExecutionPlan(
        skill_id=selected.skill_id,
        task_component=selected.task_component,
        inputs=dict(known_inputs),
        source_task=analysis.original_request,
    )
    return PlanningResult(
        status="planned",
        plan=plan,
        selected_skill_id=selected.skill_id,
        selected_binding_id=binding.binding_id,
        selected_description=binding.description,
        selected_input_schema=binding.input_schema,
        selected_input_field_groups=binding.input_field_groups,
    )
