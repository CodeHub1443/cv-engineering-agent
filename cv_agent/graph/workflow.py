"""
cv_agent.graph.workflow — Requirements-clarification + planning +
approval-gated execution workflow graph.

See ADR-0003 and ADR-0010. This is the first LangGraph topology in the repo
that uses real interrupts (`langgraph.types.interrupt`), not the minimal
`initialize -> END` stub in `cv_agent.graph.builder`. It is deliberately a
second, separate graph rather than nodes inserted into `build_graph()`'s
topology — see ADR-0003 §4 for why, and its revisit trigger for when the two
should merge.

Topology:

    START -> initialize -> analyze_requirements
                                |
                    (unanswered clarification questions
                     and clarify not yet attempted this run?)
                        yes  /        \\  no
                            v          v
                        clarify   plan_execution <──────────────────┐
                     (interrupt)       |                            │
                            \\        (ADR-0010 §3: caller-supplied  │
                             \\        pending_execution preserved   │
                              \\       as-is; otherwise derived from │
                               \\      requirements_analysis.        │(always
                                \\     skill_links)                  │ loops
                                 v                                   │ back,
                    analyze_requirements       ┌─────────────────────┤ exactly
                    (loop back, now with       │                     │ once)
                     clarification_answers     │ status ==           │
                     as assumptions)           │ "missing_required_  │
                                                │ inputs" AND not     │
                                                │ yet attempted       │
                                                v                     │
                                    provide_execution_inputs ─────────┘
                                         (interrupt, ADR-0010 §13)
                                                |
                          (already attempted this run?)
                                yes /                    \\ no
                                   v                       v
                    terminal == True?              approval_gate
                     yes /      \\ no                     |
                        v         v              (pending_execution present
                       END   approval_gate         and its binding requires
                                   |                approval?)
                                   v                   yes /      \\ no / none
                                execute                    v        v
                                   |                    execute   END
                                   v                        |
                                  END                        v
                                                             END

`clarify`, `approval_gate`, and `provide_execution_inputs` are the three
interrupt points. `plan_execution` itself never interrupts and never
executes/approves anything — it only derives `pending_execution` when the
caller hasn't already supplied one, reading any caller-supplied
`AgentState["execution_inputs"]` (ADR-0010 §12, keyed by `InputField.name`
— never `clarification_answers`, a distinct namespace keyed by
`RequirementField.name`) as its `available_inputs`.

Since ADR-0003 §9 (Q21 fix): `clarify`'s own loop bound is likewise an
explicit `AgentState["clarification_attempted"]` flag, not
`clarification_answers`' emptiness — a human who declines *every*
clarification question still counts as "attempted", so `_route_after_
analysis` does not re-raise the same interrupt indefinitely. Prior to this
fix, the bound was `clarification_answers`' own truthiness, which could not
distinguish "asked and declined everything" from "never asked" and looped
forever on the former — confirmed empirically, not theoretical.

Since ADR-0010 §13: when `plan_execution()` reports
`"missing_required_inputs"` and no recovery has been attempted yet this
run, the graph routes to `provide_execution_inputs` instead of
`approval_gate` — a third interrupt, architecturally consistent with
`clarify`, that asks a human for exactly the missing values and always
routes back to `plan_execution` for a fresh, authoritative retry (never
straight to `approval_gate` — a retry re-derives everything, it is never
assumed). This happens **at most once** per run, hard-coded
(`AgentState["execution_input_recovery"]["attempted"]`, the same explicit-
flag pattern `clarification_attempted` now also uses) — a second `"missing_
required_inputs"` result after a recovery attempt routes straight through
to the terminal check below, never a second interrupt. `pending_execution`
may be set from a recovery round **only** when the retry's freshly-selected
candidate's identity (`selected_skill_id`/`selected_binding_id`) and its
full `input_schema`/`input_field_groups` snapshot (ADR-0009 §12, ADR-0010
§14) both still match what was recorded before the human was asked
(`AgentState["execution_input_recovery"]["expected_*"]`, themselves sourced
only from the checkpointed `planning_result`, never a live registry lookup
at comparison time) — any mismatch, along with an
incomplete/invalid/cancelled answer, is a terminal outcome
(`execution_input_recovery["terminal"] is True`) that routes straight to
`END`, **bypassing `approval_gate` entirely** so a failed recovery can
never be read as "approval not required" for a plan that was never
actually produced.

Both `clarify` and `provide_execution_inputs` use LangGraph's dynamic
`interrupt()` — the node's own call pauses the graph; resuming with
`Command(resume=value)` re-enters that same node with `interrupt()`
returning `value` instead of pausing again. State (including everything
written by nodes that already ran) survives the pause because the graph is
compiled with a checkpointer, keyed by `thread_id`.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Literal, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from cv_agent.execution.binding import ExecutionBindingRegistry
from cv_agent.execution.executor import SkillExecutor
from cv_agent.execution.models import (
    ExecutionError,
    ExecutionEvidence,
    SkillExecutionRequest,
    SkillExecutionResult,
)
from cv_agent.graph.planning import plan_execution
from cv_agent.graph.state import AgentState
from cv_agent.requirements.analyzer import RequirementsAnalyzer
from cv_agent.requirements.models import RequirementsAnalysis, SkillLink
from cv_agent.skills.inventory import SkillInventory


def _append_step(state: AgentState, node: str, action: str, **extra: Any) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = list(state.get("steps", []))
    steps.append({"node": node, "action": action, **extra})
    return steps


def _make_analyze_requirements_node(analyzer: RequirementsAnalyzer):
    def _node_analyze_requirements(state: AgentState) -> dict[str, Any]:
        task = state.get("task") or ""
        assumptions = state.get("clarification_answers") or {}
        analysis = analyzer.analyze(task, assumptions=assumptions or None)
        return {
            "requirements_analysis": dataclasses.asdict(analysis),
            "status": "analyzed",
            "steps": _append_step(
                state,
                "analyze_requirements",
                "requirements_analyzed",
                unknown_fields=list(analysis.unknown_field_names),
                candidate_tasks=[t.task_component for t in analysis.candidate_tasks],
            ),
        }

    return _node_analyze_requirements


def _route_after_analysis(state: AgentState) -> Literal["clarify", "plan_execution"]:
    analysis = state.get("requirements_analysis") or {}
    questions = analysis.get("clarification_questions") or []
    # ADR-0003 §9 (Q21 fix): route on whether clarify was already attempted
    # this run, never on clarification_answers' own emptiness — an empty
    # answers dict is a legitimate "asked and declined everything" outcome,
    # not "never asked". See _node_clarify, which sets this flag
    # unconditionally on every resume, and clarification_attempted's own
    # docstring (cv_agent.graph.state) for why clarification_answers alone
    # cannot represent this distinction.
    already_attempted = bool(state.get("clarification_attempted"))
    if questions and not already_attempted:
        return "clarify"
    return "plan_execution"


def _node_clarify(state: AgentState) -> dict[str, Any]:
    analysis = state.get("requirements_analysis") or {}
    questions = analysis.get("clarification_questions") or []

    payload = {
        "type": "clarification",
        "problem_statement": analysis.get("problem_statement"),
        "questions": questions,
    }
    prompt_lines = [f"- {q['question']} (why: {q['why_it_matters']})" for q in questions]
    pending_prompt = "Clarification needed:\n" + "\n".join(prompt_lines)

    answers = interrupt(payload)
    # `answers` is whatever the caller passed to Command(resume=...) — must
    # be a mapping of field name -> answer text. An empty/None resume value
    # is treated as "no answers supplied", not fabricated. NOTE: a literal
    # empty dict `{}` (or `None`) is not reliably delivered by the installed
    # LangGraph's Command(resume=...) at all — confirmed empirically (ADR-
    # 0003 §9, Q21): the graph silently re-pauses here instead of resuming.
    # A caller declining every question must pass a non-dict falsy value
    # (e.g. `""`), same convention `provide_execution_inputs` already uses
    # — see CVAgent.resume_workflow()'s docstring.
    answers_dict: dict[str, str] = dict(answers) if answers else {}

    return {
        "clarification_answers": answers_dict,
        # ADR-0003 §9 (Q21 fix): set unconditionally, regardless of whether
        # answers_dict ended up empty — this is what lets _route_after_
        # analysis distinguish "attempted, declined everything" from "never
        # attempted", which clarification_answers' own truthiness cannot.
        "clarification_attempted": True,
        "pending_human_input": None,
        "status": "clarified",
        "steps": _append_step(
            state,
            "clarify",
            "clarification_interrupt_resumed",
            answered_fields=sorted(answers_dict.keys()),
        ),
    }


def _route_after_clarify(state: AgentState) -> Literal["analyze_requirements"]:
    # Always loop back exactly once to fold the human's answers into a
    # fresh analysis. _route_after_analysis will not route back to
    # "clarify" a second time because clarification_attempted is now set —
    # this prevents an infinite interrupt loop even if unknowns remain, and
    # even if the human declined every question (ADR-0003 §9, Q21 fix;
    # clarification_answers being empty no longer re-triggers this edge).
    return "analyze_requirements"


def _classify_execution_input_resume(
    resume_value: Any,
    requested: list[str],
    declared_names: set[str],
    field_groups: list[frozenset[str]],
) -> tuple[str, dict[str, Any], list[dict[str, str]]]:
    """
    ADR-0010 §13's deterministic classification of a `provide_execution_
    inputs` resume value, relative to `requested` (the exact, complete
    `missing_inputs` list from the one and only ask this run), `declared_
    names` (every field name the selected binding's checkpointed
    `input_schema` snapshot declares, required or not), and `field_groups`
    (ADR-0009 §12/ADR-0010 §14, resolving Q20: every still-unsatisfied
    `RequiredFieldGroup.field_names` from the checkpointed snapshot, each
    already a strict subset of `requested` since an unsatisfied group means
    every one of its members was reported missing — see the caller).

    Returns (outcome, accepted, rejected). `outcome` is one of "cancelled"/
    "invalid"/"incomplete"/"supplied" — never "binding_mismatch", which
    only `_node_plan_execution` can determine, on the retry, by comparing
    identity/schema; this function has no visibility into that.

    Fulfillment is no longer "every requested name answered": a name that
    belongs to a `field_groups` entry is satisfied the moment ANY one
    member of its group is accepted (mirroring `plan_execution()`'s own
    "exactly_one" presence check) — requiring all of `path`/`data` to be
    supplied to recover from a real XOR contract would misrepresent it.
    Every `requested` name outside any group still needs its own value, as
    before this parameter existed.

    A field attempted-but-rejected (blank, or not a declared name) and a
    field never mentioned at all are treated identically for the outcome
    verdict — both simply mean "not fulfilled" — but remain individually
    visible via `rejected` (why a given attempt failed) and the caller's
    own `still_missing` computation (`requested` minus `accepted` minus any
    already-satisfied group's other members — see the caller).
    """
    supplied: dict[str, Any] = resume_value if isinstance(resume_value, dict) else {}

    def _present(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str) and value.strip() == "":
            return False
        return True

    accepted: dict[str, Any] = {}
    rejected: list[dict[str, str]] = []
    for name, value in supplied.items():
        if name not in declared_names:
            rejected.append({"name": name, "reason": "not_declared"})
        elif not _present(value):
            rejected.append({"name": name, "reason": "blank"})
        else:
            accepted[name] = value

    accepted_names = set(accepted)
    grouped_names = set().union(*field_groups) if field_groups else set()
    ungrouped_requested = set(requested) - grouped_names

    groups_ok = all(group & accepted_names for group in field_groups)
    individual_ok = ungrouped_requested <= accepted_names
    fulfilled = accepted_names & set(requested)

    if not isinstance(resume_value, dict) or not supplied:
        outcome = "cancelled"
    elif individual_ok and groups_ok:
        outcome = "supplied"
    elif not fulfilled:
        outcome = "invalid"
    else:
        outcome = "incomplete"

    return outcome, accepted, rejected


def _make_provide_execution_inputs_node():
    def _node_provide_execution_inputs(state: AgentState) -> dict[str, Any]:
        # Everything read here, before interrupt(), comes only from the
        # already-checkpointed planning_result — never a live
        # ExecutionBindingRegistry lookup. LangGraph's dynamic interrupt()
        # re-runs a node's pre-interrupt code on resume; a live lookup here
        # would be replay-unsafe (it could observe a registry mutated
        # during the pause) and is unnecessary, since the identity/schema
        # this node needs was already captured once, safely, by
        # _node_plan_execution before this node was ever reached.
        planning = state.get("planning_result") or {}
        skill_id = planning.get("selected_skill_id")
        binding_id = planning.get("selected_binding_id")
        expected_schema_raw = planning.get("selected_input_schema") or ()
        expected_schema: list[dict[str, Any]] = [dict(f) for f in expected_schema_raw]
        expected_groups_raw = planning.get("selected_input_field_groups") or ()
        # field_names normalized to a list here (never left as whatever
        # container type the checkpoint happened to restore) so the later
        # structural comparison in _node_plan_execution's retry — this
        # dict is what gets stored verbatim into execution_input_recovery
        # below — never false-positives on a tuple-vs-list container
        # mismatch that carries no actual meaning, the same class of
        # instability ADR-0004's own CVAgent._sync_memory_after_run()
        # docstring already documents for other AgentState tuple fields.
        expected_groups: list[dict[str, Any]] = [
            {
                "kind": g["kind"],
                "field_names": list(g["field_names"]),
                "description": g.get("description", ""),
            }
            for g in expected_groups_raw
        ]
        requested = list(planning.get("missing_inputs") or ())

        payload = {
            "type": "provide_execution_inputs",
            "skill_id": skill_id,
            "binding_id": binding_id,
            "missing_inputs": [
                {"name": f["name"], "description": f.get("description", "")}
                for f in expected_schema
                if f["name"] in requested
            ],
            "field_groups": [
                {"kind": g["kind"], "field_names": g["field_names"]} for g in expected_groups
            ],
        }
        resume_value = interrupt(payload)

        declared_names = {f["name"] for f in expected_schema}
        requested_set = set(requested)
        # Every field_groups entry here is, by construction, a group whose
        # members plan_execution() found ALL missing (see plan_execution()'s
        # own docstring) — hence a strict subset of `requested`. Groups
        # already (partially) satisfied at plan time never appear in
        # missing_inputs at all, so there is nothing to reconstruct for them.
        field_groups = [
            frozenset(g["field_names"])
            for g in expected_groups
            if set(g["field_names"]) <= requested_set
        ]
        outcome, accepted, rejected = _classify_execution_input_resume(
            resume_value, requested, declared_names, field_groups
        )

        merged_execution_inputs = dict(state.get("execution_inputs") or {})
        merged_execution_inputs.update(accepted)

        # A satisfied group's OTHER, unanswered member(s) are not "still
        # missing" — the group as a whole is fulfilled the moment any one
        # member is accepted (§14.1's own rule), so e.g. supplying only
        # "data" from a path/data group must not still list "path" here.
        accepted_names = set(accepted)
        satisfied_group_members: set[str] = set()
        for group in field_groups:
            if group & accepted_names:
                satisfied_group_members |= group
        still_missing = sorted(set(requested) - accepted_names - satisfied_group_members)

        # terminal/mismatch_detail are deliberately left unset here — only
        # _node_plan_execution's retry, with a fresh plan_execution() call
        # in hand, can determine whether the identity/schema this human was
        # asked about still holds. This partial record is never externally
        # observable: provide_execution_inputs -> plan_execution is a plain
        # edge, so both nodes run inside one resume_workflow() call before
        # control ever returns to a caller.
        recovery_record: dict[str, Any] = {
            "attempted": True,
            "outcome": outcome,
            "terminal": None,
            "mismatch_detail": None,
            "expected_skill_id": skill_id,
            "expected_binding_id": binding_id,
            "expected_input_schema": expected_schema,
            "expected_input_field_groups": expected_groups,
            "requested": requested,
            "accepted": sorted(accepted.keys()),
            "still_missing": still_missing,
            "rejected": rejected,
        }

        return {
            "execution_inputs": merged_execution_inputs,
            "execution_input_recovery": recovery_record,
            "pending_human_input": None,
            "steps": _append_step(
                state,
                "provide_execution_inputs",
                "execution_input_interrupt_resumed",
                outcome=outcome,
                requested=requested,
                accepted=sorted(accepted.keys()),
            ),
        }

    return _node_provide_execution_inputs


def _skill_link_from_dict(d: dict[str, Any]) -> SkillLink:
    return SkillLink(
        task_component=d["task_component"],
        skill_id=d["skill_id"],
        declared=d["declared"],
        matched_terms=tuple(d.get("matched_terms") or ()),
        executable=d["executable"],
    )


def _requirements_analysis_for_planning(analysis_dict: dict[str, Any]) -> RequirementsAnalysis:
    """
    Reconstructs just enough of `RequirementsAnalysis` for `plan_execution()`
    (ADR-0010) to read — `original_request` and `skill_links` are the only
    two fields it touches. `AgentState["requirements_analysis"]` stores
    `dataclasses.asdict()` output (ADR-0003 §3), never the dataclass
    instance itself, so this adapts that dict back into the type
    `plan_execution()`'s signature requires — `cv_agent.graph.planning`
    itself is not changed by this. Every other `RequirementsAnalysis` field
    is filled with a cheap, unused placeholder: never read by
    `plan_execution()`, never written back into `AgentState`.

    Robust to `skill_links`'/`matched_terms`' container type: ADR-0004's own
    `CVAgent._sync_memory_after_run()` docstring already documents that
    `AgentState`'s tuple fields come back as lists once state has been
    through a LangGraph checkpoint save/restore — this reconstruction only
    ever iterates them, never assumes tuple vs. list.
    """
    skill_links = tuple(
        _skill_link_from_dict(d) for d in (analysis_dict.get("skill_links") or ())
    )
    return RequirementsAnalysis(
        original_request=analysis_dict.get("original_request") or "",
        problem_statement="",
        fields=(),
        candidate_tasks=(),
        capability_links=(),
        skill_links=skill_links,
        clarification_questions=(),
        assumptions=(),
        constraints=(),
        risks=(),
    )


def _make_plan_execution_node(execution_registry: ExecutionBindingRegistry):
    def _node_plan_execution(state: AgentState) -> dict[str, Any]:
        existing_pending = state.get("pending_execution")
        if existing_pending is not None:
            # An already-supplied pending_execution — the pre-existing
            # start_workflow(pending_execution=...) contract (ADR-0003 §3)
            # — is explicit, caller-supplied intent. It always takes
            # precedence over this node's own automatic derivation from
            # skill_links and is never overwritten: ADR-0010's planner has
            # no opinion about, and no visibility into, intent a caller
            # already expressed more directly than "let the deterministic
            # rule pick." Nothing about this is a bypass of plan_execution()
            # — it simply means there is nothing for this node to derive.
            #
            # planning_result (ADR-0010 §11) is deliberately left unset
            # here, not set to some ad-hoc "skipped" placeholder — no
            # plan_execution() call was made, so there is no PlanningResult
            # to report; a caller-supplied plan was never a planning
            # decision. This "steps" entry remains the record of why.
            return {
                "steps": _append_step(
                    state, "plan_execution", "caller_supplied_pending_execution_preserved"
                ),
            }

        analysis_dict = state.get("requirements_analysis") or {}
        analysis = _requirements_analysis_for_planning(analysis_dict)
        # available_inputs (ADR-0010 §12): AgentState["execution_inputs"] is
        # the one legitimate source — caller-supplied, keyed by
        # InputField.name, set via start_workflow(execution_inputs=...)
        # and/or merged in by provide_execution_inputs on a recovery resume
        # (ADR-0010 §13, same field, same contract). clarification_answers
        # is a different namespace (keyed by RequirementField.name) and is
        # never read here or folded in — doing so would be exactly the
        # "infer execution inputs from arbitrary text" this node must not
        # do (ADR-0010 §3).
        available_inputs = state.get("execution_inputs") or {}
        result = plan_execution(analysis, execution_registry, available_inputs=available_inputs)

        recovery = state.get("execution_input_recovery")
        already_attempted = recovery is not None and recovery.get("attempted") is True

        updated_recovery: Optional[dict[str, Any]] = None
        plan_allowed = result.status == "planned"

        if already_attempted:
            # Retry after a provide_execution_inputs interrupt resumed
            # (ADR-0010 §13). This is the ONLY place pending_execution may
            # be set from a recovery round, and it is gated on an explicit,
            # re-derived comparison against the checkpointed expected_*
            # values recorded before the human was ever asked — never on
            # trusting the interrupt node's own raw classification, and
            # never on ID equality alone (a same-binding_id schema could
            # still have changed shape/meaning underneath).
            assert recovery is not None
            expected_schema = list(recovery.get("expected_input_schema") or [])
            fresh_schema = [
                dataclasses.asdict(f) for f in (result.selected_input_schema or ())
            ]
            expected_groups = list(recovery.get("expected_input_field_groups") or [])
            # Built manually, field_names forced to list() — NOT
            # dataclasses.asdict(), which would preserve field_names as a
            # tuple here (a fresh, non-checkpoint-restored RequiredFieldGroup)
            # while `expected_groups` above was normalized to a list when
            # recorded; comparing tuple against list would false-positive a
            # "schema_changed" mismatch for a binding that never changed.
            fresh_groups = [
                {"kind": g.kind, "field_names": list(g.field_names), "description": g.description}
                for g in (result.selected_input_field_groups or ())
            ]
            identity_ok = (
                result.selected_skill_id == recovery.get("expected_skill_id")
                and result.selected_binding_id == recovery.get("expected_binding_id")
            )
            # ADR-0010 §14: field groups are part of the same structural
            # contract snapshot as input_schema — a binding whose individual
            # fields are unchanged but whose group constraints were altered
            # underneath the pause must still be caught here, not just by
            # comparing input_schema alone.
            schema_ok = fresh_schema == expected_schema and fresh_groups == expected_groups
            raw_outcome: Any = recovery.get("outcome")

            final_outcome: str
            terminal: bool
            detail: Optional[str]
            if not identity_ok:
                final_outcome, terminal, detail = "binding_mismatch", True, "identity_changed"
            elif not schema_ok:
                final_outcome, terminal, detail = "binding_mismatch", True, "schema_changed"
            elif raw_outcome != "supplied":
                final_outcome, terminal, detail = raw_outcome, True, None
            elif result.status != "planned":
                # Invariant/safety guard, not a reachable branch under
                # normal operation (verified on PR #33 review, extended for
                # field groups in ADR-0010 §14): if identity_ok and
                # schema_ok both hold, every requested name is, by
                # construction, either a required field or a member of a
                # group of the (unchanged) selected binding, and the
                # interrupt node's own "supplied" classification already
                # means every individually-required name — and at least one
                # member of every group — has a valid value in the
                # now-merged execution_inputs — so plan_execution()'s own
                # missing-field/group check (ADR-0010 §3/§14) cannot find
                # anything unsatisfied, and result.status must be "planned".
                # This branch exists only
                # to keep the "never fabricate a plan" guarantee
                # unconditional rather than dependent on that reasoning
                # continuing to hold as the codebase evolves — belt and
                # suspenders, deliberately kept even though no test
                # constructs a real scenario that reaches it.
                final_outcome, terminal, detail = (
                    "binding_mismatch",
                    True,
                    "still_incomplete_after_supply",
                )
            else:
                final_outcome, terminal, detail = "supplied", False, None

            updated_recovery = {
                **recovery,
                "outcome": final_outcome,
                "terminal": terminal,
                "mismatch_detail": detail,
            }
            plan_allowed = final_outcome == "supplied" and not terminal

        pending: Optional[dict[str, Any]] = None
        log_extra: dict[str, Any] = {"planning_status": result.status}
        if plan_allowed:
            assert result.status == "planned" and result.plan is not None
            pending = {
                "skill_id": result.plan.skill_id,
                "inputs": result.plan.inputs,
                "task": result.plan.source_task,
            }
            log_extra["skill_id"] = result.plan.skill_id
            log_extra["task_component"] = result.plan.task_component
        elif result.status == "ambiguous_candidates":
            log_extra["candidate_skill_ids"] = list(result.candidate_skill_ids)
        elif result.status == "missing_required_inputs":
            log_extra["missing_inputs"] = list(result.missing_inputs)

        if updated_recovery is not None:
            log_extra["recovery_outcome"] = updated_recovery["outcome"]
            log_extra["recovery_terminal"] = updated_recovery["terminal"]

        update: dict[str, Any] = {
            "pending_execution": pending,
            "planning_result": dataclasses.asdict(result),
            "steps": _append_step(state, "plan_execution", "planning_attempted", **log_extra),
        }
        if updated_recovery is not None:
            update["execution_input_recovery"] = updated_recovery
            if updated_recovery["terminal"]:
                # This node's own conditional edge (_route_after_planning)
                # sends a terminal recovery outcome straight to END,
                # bypassing approval_gate entirely — the one node that
                # would otherwise have set status="done" for a no-plan run.
                # Set it here so a terminal recovery failure still reaches
                # the same lifecycle status ordinary completion does.
                update["status"] = "done"
        return update

    return _node_plan_execution


def _route_after_planning(state: AgentState) -> str:
    planning = state.get("planning_result")
    if planning is None:
        # Caller-supplied pending_execution (ADR-0010 §10) — no
        # plan_execution() call was ever made, so there is nothing for
        # recovery to engage with. Unchanged from before ADR-0010 §13.
        return "approval_gate"

    recovery = state.get("execution_input_recovery")
    already_attempted = recovery is not None and recovery.get("attempted") is True

    if planning.get("status") == "missing_required_inputs" and not already_attempted:
        return "provide_execution_inputs"

    if already_attempted:
        # A recovery round just finalized (or this pass is the retry that
        # follows one). terminal is the single, authoritative signal — an
        # incomplete/invalid/cancelled/binding_mismatch outcome bypasses
        # approval_gate entirely, so a failed recovery can never be read as
        # "approval not required" for a plan that was never produced.
        assert recovery is not None
        return END if recovery.get("terminal") else "approval_gate"

    # First-pass planned / no_executable_candidate / ambiguous_candidates —
    # unchanged from before ADR-0010 §13.
    return "approval_gate"


def _make_approval_gate_node(executor: SkillExecutor):
    def _node_approval_gate(state: AgentState) -> dict[str, Any]:
        pending = state.get("pending_execution")
        if pending is None:
            return {
                "approval_decision": "not_required",
                "status": "done",
                "steps": _append_step(state, "approval_gate", "no_pending_execution"),
            }

        binding = executor.get_binding(pending["skill_id"])
        if binding is None or binding.approval_policy != "approval_required":
            return {
                "approval_decision": "not_required",
                "steps": _append_step(
                    state, "approval_gate", "approval_not_required", skill_id=pending["skill_id"]
                ),
            }

        payload = {
            "type": "approval",
            "skill_id": pending["skill_id"],
            "binding_id": binding.binding_id,
            "task": pending.get("task"),
            "inputs": pending.get("inputs", {}),
        }
        decision = interrupt(payload)
        # The interrupt/resume state IS the source of the decision — no
        # other code path may set approval_decision to "approved". Anything
        # that isn't exactly "approved" is treated as rejected; there is no
        # ambiguous/ silent-approve outcome.
        normalized: str = "approved" if decision == "approved" else "rejected"

        return {
            "approval_decision": normalized,
            "pending_human_input": None,
            "steps": _append_step(
                state,
                "approval_gate",
                "approval_interrupt_resumed",
                skill_id=pending["skill_id"],
                decision=normalized,
            ),
        }

    return _node_approval_gate


def _route_after_approval(state: AgentState) -> str:
    if state.get("pending_execution") is not None:
        return "execute"
    return END


def _make_execute_node(executor: SkillExecutor, skill_inventory: SkillInventory):
    def _node_execute(state: AgentState) -> dict[str, Any]:
        pending = state["pending_execution"]
        skill_id = pending["skill_id"]
        decision = state.get("approval_decision")
        approved = decision in ("approved", "not_required")

        skill = skill_inventory.get(skill_id)
        if skill is None:
            result = SkillExecutionResult(
                skill_id=skill_id,
                status="not_executable",
                evidence=ExecutionEvidence(None, None, None, None),
                error=ExecutionError(
                    "no_binding", f"'{skill_id}' was not found by skill discovery."
                ),
            )
        else:
            request = SkillExecutionRequest(
                inputs=pending.get("inputs", {}),
                task=pending.get("task"),
                approved=approved,
            )
            result = executor.execute(skill, request)

        return {
            "execution_result": dataclasses.asdict(result),
            "status": "done",
            "steps": _append_step(
                state, "execute", "execution_attempted", skill_id=skill_id, result_status=result.status
            ),
        }

    return _node_execute


def _node_initialize(state: AgentState) -> dict[str, Any]:
    return {
        "status": "ready",
        "error": None,
        "steps": _append_step(state, "initialize", "workflow_started"),
    }


def build_requirements_workflow_graph(
    *,
    requirements_analyzer: RequirementsAnalyzer,
    executor: SkillExecutor,
    skill_inventory: SkillInventory,
    execution_registry: ExecutionBindingRegistry,
    checkpointer: Optional[Any] = None,
) -> Any:
    """
    Build and compile the requirements-clarification + planning +
    approval-gated execution workflow graph.

    Kept separate from `cv_agent.graph.builder.build_graph()` (the minimal
    Step-1 topology) — see ADR-0003 §4. Every collaborator is injected, not
    imported/constructed here, so tests can pass fakes (fake analyzer,
    fake executor with fake bindings) without touching the real skill
    environment or capability registry.

    `execution_registry` (new, ADR-0010) is the same `ExecutionBindingRegistry`
    `executor` was built from — passed separately, not read off `executor`,
    because `plan_execution()` (ADR-0010 §3) depends only on the registry's
    inspect-only `get_binding()`, never on `SkillExecutor` itself; `executor`
    exposes no public accessor for its own registry, and adding one would be
    changing `SkillExecutor`, which this step does not do.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    builder: StateGraph = StateGraph(AgentState)

    builder.add_node("initialize", _node_initialize)
    builder.add_node("analyze_requirements", _make_analyze_requirements_node(requirements_analyzer))
    builder.add_node("clarify", _node_clarify)
    builder.add_node("plan_execution", _make_plan_execution_node(execution_registry))
    builder.add_node("provide_execution_inputs", _make_provide_execution_inputs_node())
    builder.add_node("approval_gate", _make_approval_gate_node(executor))
    builder.add_node("execute", _make_execute_node(executor, skill_inventory))

    builder.add_edge(START, "initialize")
    builder.add_edge("initialize", "analyze_requirements")
    builder.add_conditional_edges(
        "analyze_requirements",
        _route_after_analysis,
        {"clarify": "clarify", "plan_execution": "plan_execution"},
    )
    builder.add_conditional_edges(
        "clarify", _route_after_clarify, {"analyze_requirements": "analyze_requirements"}
    )
    builder.add_conditional_edges(
        "plan_execution",
        _route_after_planning,
        {
            "provide_execution_inputs": "provide_execution_inputs",
            "approval_gate": "approval_gate",
            END: END,
        },
    )
    builder.add_edge("provide_execution_inputs", "plan_execution")
    builder.add_conditional_edges(
        "approval_gate", _route_after_approval, {"execute": "execute", END: END}
    )
    builder.add_edge("execute", END)

    return builder.compile(checkpointer=checkpointer)
