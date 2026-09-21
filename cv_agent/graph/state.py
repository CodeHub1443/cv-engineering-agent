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

    clarification_attempted: bool
    """True once the `clarify` interrupt has been resumed at least once
    this run, regardless of whether any answers were actually supplied —
    distinct from `clarification_answers`' own non-emptiness, which cannot
    represent "asked and declined everything" versus "never asked yet".
    Set unconditionally by `_node_clarify` on every resume, mirroring
    `execution_input_recovery["attempted"]`'s existing bound in the same
    file (ADR-0010 §13). `_route_after_analysis` routes on this flag, not
    on `clarification_answers` truthiness — see ADR-0003 §9 (Q21 fix)."""

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

    Set via an explicit `CVAgent.start_workflow(execution_inputs=...)`
    argument (ADR-0010 §12) — empty (`{}`) by default, never inferred or
    pre-filled by any node. `plan_execution` reads this verbatim as
    `plan_execution()`'s `available_inputs` parameter. Since ADR-0010 §13,
    this dict is also the one place `provide_execution_inputs` (a
    same-session recovery interrupt, see `execution_input_recovery` below)
    merges a human-supplied value into, on resume — still never inferred
    from `clarification_answers`, still the exact same namespace/contract
    as the pre-supplied case, just a second, later write source for the
    same field. `docs/state/OPEN_QUESTIONS.md` Q17 is resolved by §13 for
    the "missing value discovered only after planning" case; see §13's own
    documented scope for what remains a fresh-run-only limitation (a second
    interrupt/resume round is never offered)."""

    # ── Planning (ADR-0010) ──────────────────────────────────────────────
    planning_result: Optional[dict[str, Any]]
    """`dataclasses.asdict()` of the `PlanningResult` (`cv_agent.graph.
    planning`) produced by the most recent actual `plan_execution()` call
    this run — same serialization rationale as `requirements_analysis`/
    `execution_result` below. Shape: `{"status": PlanningStatus, "plan":
    dict | None, "candidate_skill_ids": tuple/list[str],
    "candidate_descriptions": tuple/list[str], "candidate_binding_ids":
    tuple/list[str], "missing_inputs": tuple/list[str],
    "conflicting_inputs": tuple/list[str]}` (tuple on a
    fresh, non-checkpoint-restored run; may come back as a list after a
    checkpoint save/restore, same instability `requirements_analysis`'s own
    tuple fields already have — see `CVAgent._sync_memory_after_run()`);
    `plan`/`candidate_skill_ids`/`candidate_descriptions`/`missing_inputs`/
    `conflicting_inputs` are only meaningfully populated for the
    `PlanningStatus` value they document (see `cv_agent.graph.planning.
    PlanningResult`) — `candidate_descriptions`/`candidate_binding_ids`
    (ADR-0010 §16, resolving Q18) are the same order/length as
    `candidate_skill_ids`, set only for status == "ambiguous_candidates";
    `conflicting_inputs` (ADR-0010 §15, Q20 true-XOR correction) is set only
    for status == "conflicting_inputs", never alongside `missing_inputs` in
    the same result.

    `plan` is additionally forced to `None` whenever a recovery round
    (`candidate_selection` or `execution_input_recovery`) finalizes as a
    TERMINAL failure this run (ADR-0010 §16.7): the fresh planning call may
    still have produced a "planned" result — e.g. for the *other* candidate
    after the chosen skill vanished — but a run with no executable intent
    must not carry a plan a reader could mistake for one. `status` and the
    `candidate_*`/`selected_*` fields are kept as diagnostics of what that
    fresh call resolved; they describe planning's result, not intent — the
    recovery record and `pending_execution is None` are the authority.

    `None` has two causes, exactly the same ambiguity `execution_result`
    already carries for `execute`: this run's `plan_execution` node has
    not run yet, OR it ran but *skipped* calling `plan_execution()` entirely
    because `pending_execution` was already caller-supplied (ADR-0010 §10)
    — a caller-supplied plan is never a `plan_execution()` decision, so
    there is no `PlanningResult` to report for it. `steps` still carries a
    `"caller_supplied_pending_execution_preserved"` entry for that case,
    same as before this field existed.

    Since ADR-0010 §13: also carries `selected_skill_id`/
    `selected_binding_id`/`selected_input_schema`, populated whenever
    exactly one candidate was selected (status "planned",
    "missing_required_inputs", or "conflicting_inputs") — see
    `cv_agent.graph.planning.PlanningResult`. Since ADR-0010 §14 (Q20): also carries
    `selected_input_field_groups`, the same snapshot pattern for
    `ExecutionBinding.input_field_groups` (ADR-0009 §12). This is what
    `execution_input_recovery` below compares against on a retry."""

    # ── Execution-input recovery (ADR-0010 §13) ──────────────────────────
    execution_input_recovery: Optional[dict[str, Any]]
    """Same-session recovery from `planning_result.status ==
    "missing_required_inputs"` via a third interrupt kind,
    `provide_execution_inputs` — architecturally consistent with `clarify`
    but a distinct namespace: it only ever reads/writes `execution_inputs`
    above, never `clarification_answers`, and never infers one from the
    other (`[P§35]`). Limited to exactly one interrupt/resume round per
    workflow run — a partial, invalid, cancelled, or conflicting answer is
    a terminal outcome, never a second prompt.

    Shape: `{"attempted": bool, "outcome": "supplied" | "incomplete" |
    "invalid" | "cancelled" | "conflicting" | "binding_mismatch",
    "terminal": bool | None, "mismatch_detail": "identity_changed" |
    "schema_changed" | "description_changed" | "still_incomplete_after_supply" |
    "conflicting_inputs_supplied" | None, "expected_skill_id": str,
    "expected_binding_id": str, "expected_description": str | None,
    "expected_input_schema": list[dict],
    "expected_input_field_groups": list[dict], "requested": list[str],
    "accepted": list[str], "still_missing": list[str], "conflicting":
    list[str], "rejected": list[dict]}`. `expected_input_field_groups`
    (ADR-0009 §12/ADR-0010 §14, Q20) is the same checkpointed-snapshot
    pattern as `expected_input_schema` — a group counts as fulfilled only
    when EXACTLY one of its member names is supplied (ADR-0010 §15, true
    oneOf/XOR semantics): zero is folded into the ordinary "missing"
    handling, two or more is `"conflicting"` — `conflicting` names the
    member(s) supplied together that violate the constraint, a distinct
    field from `still_missing` (never populated for the same group
    simultaneously).

    Field ownership/timeline: `provide_execution_inputs` writes the record
    once, on resume, reading `expected_skill_id`/`expected_binding_id`/
    `expected_input_schema`/`requested` **only** from the already-
    checkpointed `planning_result` — never a live `ExecutionBindingRegistry`
    lookup, which would be replay-unsafe (LangGraph's dynamic `interrupt()`
    re-runs a node's pre-interrupt code on resume; nothing this node reads
    before `interrupt()` may depend on a live, mutable object). `outcome`
    at this point is never `"binding_mismatch"` and `terminal` is left
    `None` — both are finalized only by `plan_execution` on the retry this
    always routes back to, which is the *only* place `pending_execution`
    may be set from a recovery round: gated on comparing the fresh
    `plan_execution()` call's `selected_skill_id`/`selected_binding_id`/
    `selected_input_schema` against this record's checkpointed
    `expected_*` fields, structurally, not by ID equality alone. This
    intermediate/unfinalized shape is never externally observable —
    `provide_execution_inputs -> plan_execution` is a plain edge, so both
    nodes run inside one `resume_workflow()` call.

    Terminal contract: `terminal is True` for every outcome except
    `"supplied"` with a confirmed identity+schema match. When `terminal`,
    `pending_execution`/`approval_decision`/`execution_result` are all
    guaranteed `None` — the run reaches `status == "done"` without ever
    calling `approval_gate` or `execute`. A caller distinguishes a
    recovery-failure terminal from ordinary completion by checking
    `execution_input_recovery.get("terminal")` alone, without reasoning
    about the nullability of unrelated fields."""

    # ── Candidate disambiguation (ADR-0010 §16, resolving Q18) ───────────
    candidate_choice: Optional[str]
    """A validated human choice among `planning_result.candidate_skill_ids`
    (status == "ambiguous_candidates"), fed into `plan_execution()`'s
    `selected_skill_id` parameter on the retry `choose_candidate` always
    routes back to — a deliberately distinct namespace from
    `execution_inputs`/`clarification_answers`: an `InputField.name` or a
    `RequirementField.name` and a `skill_id` mean different things, and
    conflating them would be exactly the kind of silent inference `[P§35]`
    forbids. Only ever set by `choose_candidate` on a `"selected"`
    classification (never on invalid/cancelled) — `None` by default,
    never inferred or pre-filled."""

    candidate_selection: Optional[dict[str, Any]]
    """Same-session recovery from `planning_result.status ==
    "ambiguous_candidates"` via a fourth interrupt kind, `choose_candidate`
    — architecturally consistent with `clarify`/`provide_execution_inputs`
    (ADR-0003/ADR-0010 §13) but its own distinct namespace: it only ever
    reads/writes `candidate_choice` above, never `execution_inputs`/
    `clarification_answers`. Limited to exactly one interrupt/resume round
    per workflow run — an invalid, cancelled, or no-longer-valid choice is
    a terminal outcome, never a second prompt.

    Shape: `{"attempted": bool, "outcome": "selected" | "invalid" |
    "cancelled" | "candidate_mismatch" | "malformed_offer", "terminal":
    bool | None, "expected_candidate_skill_ids": list[str],
    "expected_binding_id": str | None, "expected_description": str | None,
    "chosen_skill_id": str | None, "mismatch_detail": str | None}`.
    `expected_binding_id`/`expected_description` (ADR-0010 §16.3, audit
    finding D1) pin the choice to the exact binding *shown* to the human —
    the chosen candidate's `binding_id` and description from the same
    checkpointed snapshot — so a same-`skill_id` re-registration during the
    pause cannot run something the human never saw; both are `None` unless
    the choice was `"selected"`. `mismatch_detail` names why a
    `"candidate_mismatch"` happened: `"skill_not_resolved"`,
    `"binding_changed"` (different `binding_id`) or `"description_changed"`
    (same `binding_id`, different description); for `"malformed_offer"`
    (the offer lists disagreed or were empty — the node fails closed
    *before* prompting, so no human ever sees a truncated list) it is a
    human-readable diagnostic. `expected_candidate_skill_ids` is the exact, checkpointed set
    that was actually offered — read only from the already-checkpointed
    `planning_result` before `interrupt()`, never a live
    `ExecutionBindingRegistry` lookup, the same replay-safety rule
    `provide_execution_inputs` already documents (LangGraph's dynamic
    `interrupt()` re-runs a node's pre-interrupt code on resume).

    `outcome` at write time is never `"candidate_mismatch"` and `terminal`
    is left `None` — both are finalized only by `plan_execution` on the
    retry this always routes back to: a fresh, authoritative
    `plan_execution(..., selected_skill_id=candidate_choice)` call either
    resolves the ambiguity (the choice was real and the registry has not
    changed underneath the pause) or still reports
    `"ambiguous_candidates"` — the latter becomes `"candidate_mismatch"`,
    terminal, never a fabricated resolution. This is the *only* place
    `candidate_choice`'s validity against the *current* registry state is
    confirmed — the interrupt node's own `"selected"` classification only
    proves the choice matched what was offered at ask time, not that it
    still resolves anything now.

    Terminal contract: identical in shape and meaning to
    `execution_input_recovery`'s own — `terminal is True` for every
    outcome except `"selected"` with a confirmed match; when `terminal`,
    `pending_execution`/`approval_decision`/`execution_result` are all
    guaranteed `None`, the run reaches `status == "done"` without ever
    calling `approval_gate` or `execute`."""

    # ── Approval + execution (ADR-0003, ADR-0009) ───────────────────────────
    pending_execution: Optional[dict[str, Any]]
    """What the caller is asking the graph to (attempt to) execute, if
    anything this run: `{"skill_id": str, "inputs": dict, "task": str |
    None, "execution_pin": dict | None}`. None means this run does not touch
    execution at all.

    `execution_pin` (ADR-0003 section 10, issue #43) is the immutable
    execution snapshot, written once by `_node_plan_execution` in the same
    update as the plan and never re-captured. Exactly one of three states:
    key MISSING (never pinned - only by bypassing `plan_execution`), explicit
    `None` (no binding registered at capture - nothing can execute), or a
    dict `{"binding": <canonical ExecutionBinding snapshot>,
    "runtime_generation": int | None}`, well-formed or malformed. Missing and
    malformed are unusable: no approval interrupt, no execution."""

    approval_decision: Optional[str]
    """"approved" | "rejected" | "not_required" | None (not yet decided).
    Set only by the approval-gate node from the value an `interrupt()` call
    actually receives on resume — never inferred, never defaulted to
    "approved". See ADR-0003 §5. Since ADR-0003 section 10 it is derived from
    the pinned policy only (never a live registry read), stays `None` for a
    missing/malformed pin, and is never rewritten after the gate: a recorded
    "rejected" is terminal and integrity failures write `execution_result`
    only."""

    execution_result: Optional[dict[str, Any]]
    """`dataclasses.asdict()` of the `SkillExecutionResult` produced by
    `cv_agent.execution.SkillExecutor.execute()`, if the execute node ran.
    Same serialization rationale as `requirements_analysis`."""
