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

Since ADR-0010 §16 (Q18): a fourth interrupt, `choose_candidate`, sits
*before* `provide_execution_inputs` on the same `plan_execution` fan-out —

    plan_execution ──status == "ambiguous_candidates" AND candidate
                     selection not yet attempted──> choose_candidate ──┐
         ^                                                             │
         └─────────────────────────── (always loops back) ─────────────┘

`plan_execution` cannot evaluate a candidate's input completeness until
exactly one candidate is selected, so an unresolved ambiguity always takes
routing priority. The human's resume value is a bare `skill_id` string,
validated against the exact checkpointed set that was offered
(`candidate_choice` / `candidate_selection` in `AgentState`); the retry's
fresh `plan_execution(..., selected_skill_id=...)` call independently
re-confirms it against the current registry. Like every other interrupt
here it is one-shot: an invalid, cancelled, or no-longer-valid choice is a
terminal outcome routing straight to `END`, bypassing `approval_gate`,
never a silent default.

`clarify`, `approval_gate`, `provide_execution_inputs`, and
`choose_candidate` are the four interrupt points (`clarify`/
`provide_execution_inputs`/`choose_candidate` each bounded to one round per
run). `plan_execution` itself never interrupts and never
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
incomplete/invalid/cancelled/conflicting answer (ADR-0010 §15: two or more
members of an "exactly_one" `RequiredFieldGroup` supplied together), is a
terminal outcome
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

from cv_agent.execution.binding import ExecutionBindingRegistry, pin_is_well_formed
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


def _classify_candidate_choice(
    resume_value: Any, candidate_skill_ids: list[str]
) -> tuple[str, Optional[str]]:
    """
    ADR-0010 §16's deterministic classification of a `choose_candidate`
    resume value, relative to `candidate_skill_ids` (the exact, complete
    set of candidates actually offered — the checkpointed `planning_result.
    candidate_skill_ids` snapshot from the one and only ask this run, never
    a live registry re-derivation; see the caller).

    Returns (outcome, chosen_skill_id). `outcome` is one of "cancelled"/
    "invalid"/"selected" — never "candidate_mismatch", which only
    `_node_plan_execution` can determine, on the retry, by re-running
    `plan_execution()` against the *current* registry state; this function
    has no visibility into that (mirrors `_classify_execution_input_resume`'s
    own split between what a per-round check can know and what only a
    fresh, authoritative retry can confirm).

    A resume value that isn't a non-blank string at all (`""`, `"   "`, `[]`,
    `False`, `0`, a non-empty dict, anything else that reaches this
    function) is "cancelled" — never coerced, never guessed. A non-blank
    string that doesn't name one of `candidate_skill_ids` exactly is
    "invalid" — this function never picks the "closest" match or falls back
    to any candidate; `[P§35]` forbids silently choosing one for the human.

    What does NOT reach this function as an ordinary "cancelled" answer:
    `None` and a literal empty dict `{}`. That is the installed LangGraph's
    own `Command(resume=...)` behavior, not something this node does — the
    same characteristic `CVAgent.resume_workflow()`'s docstring already
    documents for `clarify`/`provide_execution_inputs`, confirmed here for
    this interrupt by test: `resume={}` is not delivered and the graph
    silently re-pauses at this same interrupt (nothing finalized, nothing
    executed, a later valid answer still works), and `resume=None` raises
    inside LangGraph itself (`UnboundLocalError`). This PR deliberately does
    not work around either; a caller declining must pass a non-`None`,
    non-`{}` falsy value such as `""` (which is what the CLI does).
    """
    if not isinstance(resume_value, str) or not resume_value.strip():
        return "cancelled", None
    chosen = resume_value.strip()
    if chosen not in candidate_skill_ids:
        return "invalid", None
    return "selected", chosen


def _make_choose_candidate_node():
    def _node_choose_candidate(state: AgentState) -> dict[str, Any]:
        # Everything read here, before interrupt(), comes only from the
        # already-checkpointed planning_result — never a live
        # ExecutionBindingRegistry lookup. Same replay-safety rule
        # _node_provide_execution_inputs already documents: LangGraph's
        # dynamic interrupt() re-runs a node's pre-interrupt code on
        # resume, so nothing read here may depend on a live, mutable
        # object that could have changed during the pause.
        planning = state.get("planning_result") or {}
        candidate_ids = list(planning.get("candidate_skill_ids") or ())
        candidate_descriptions = list(planning.get("candidate_descriptions") or ())
        candidate_binding_ids = list(planning.get("candidate_binding_ids") or ())

        # Fail closed on a malformed offer (audit finding D4): the three
        # parallel lists must be non-empty and the same length, or the
        # human would be shown a truncated list (zip() silently drops the
        # tail) while validation still accepted the hidden IDs. Checked
        # BEFORE interrupt() and from checkpointed state only, so it is
        # replay-safe and never prompts with a partial offer. plan_execution()
        # always builds equal-length lists, so this is unreachable today —
        # it exists so a future producer/checkpoint that breaks the
        # invariant is a loud terminal diagnostic, never a silent one.
        if not candidate_ids or not (
            len(candidate_ids) == len(candidate_descriptions) == len(candidate_binding_ids)
        ):
            return {
                "candidate_selection": {
                    "attempted": True,
                    "outcome": "malformed_offer",
                    "terminal": True,
                    "expected_candidate_skill_ids": candidate_ids,
                    "expected_binding_id": None,
                    "expected_description": None,
                    "chosen_skill_id": None,
                    "mismatch_detail": (
                        f"offer lists disagree: {len(candidate_ids)} skill_ids, "
                        f"{len(candidate_descriptions)} descriptions, "
                        f"{len(candidate_binding_ids)} binding_ids"
                    ),
                },
                "pending_human_input": None,
                "status": "done",
                "steps": _append_step(
                    state, "choose_candidate", "candidate_offer_malformed_terminal"
                ),
            }

        candidates = [
            {"skill_id": skill_id, "description": description}
            for skill_id, description in zip(candidate_ids, candidate_descriptions)
        ]

        payload = {
            "type": "choose_candidate",
            "candidates": candidates,
        }
        resume_value = interrupt(payload)
        outcome, chosen = _classify_candidate_choice(resume_value, candidate_ids)

        # The chosen candidate's identity AS SHOWN — binding_id and
        # description — read from the same checkpointed snapshot the human
        # was offered, never a live registry lookup (replay-safe, same rule
        # as above). The retry in _node_plan_execution pins the choice to
        # exactly this (audit finding D1).
        expected_binding_id: Optional[str] = None
        expected_description: Optional[str] = None
        if chosen is not None:
            chosen_index = candidate_ids.index(chosen)
            expected_binding_id = candidate_binding_ids[chosen_index]
            expected_description = candidate_descriptions[chosen_index]

        # terminal is deliberately left unset here — only
        # _node_plan_execution's retry, with a fresh plan_execution() call
        # in hand, can determine whether this choice still resolves
        # ambiguity against the current registry. This partial record is
        # never externally observable: choose_candidate -> plan_execution
        # is a plain edge, so both nodes run inside one resume_workflow()
        # call before control ever returns to a caller.
        recovery_record: dict[str, Any] = {
            "attempted": True,
            "outcome": outcome,
            "terminal": None,
            "expected_candidate_skill_ids": candidate_ids,
            "expected_binding_id": expected_binding_id,
            "expected_description": expected_description,
            "chosen_skill_id": chosen,
            "mismatch_detail": None,
        }

        update: dict[str, Any] = {
            "candidate_selection": recovery_record,
            "pending_human_input": None,
            "steps": _append_step(
                state,
                "choose_candidate",
                "candidate_interrupt_resumed",
                outcome=outcome,
                chosen_skill_id=chosen,
            ),
        }
        if chosen is not None:
            update["candidate_choice"] = chosen
        return update

    return _node_choose_candidate


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
    "invalid"/"incomplete"/"conflicting"/"supplied" — never
    "binding_mismatch", which only `_node_plan_execution` can determine, on
    the retry, by comparing identity/schema; this function has no
    visibility into that.

    True oneOf/XOR fulfillment (ADR-0010 §15, correcting an earlier
    "at least one" version): a `field_groups` entry is satisfied only when
    EXACTLY one of its members is accepted — zero accepted is "not
    fulfilled" (folds into "invalid"/"incomplete" below, same as any other
    unanswered `requested` name); two or more accepted together is
    "conflicting", checked and returned ahead of "supplied"/"invalid"/
    "incomplete" even if some other part of `requested` was answered fine,
    since a contradictory answer needs correcting regardless. Every
    `requested` name outside any group still needs its own single value,
    unchanged from before this parameter existed.

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

    any_group_conflicting = any(len(group & accepted_names) > 1 for group in field_groups)
    groups_ok = all(len(group & accepted_names) == 1 for group in field_groups)
    individual_ok = ungrouped_requested <= accepted_names
    fulfilled = accepted_names & set(requested)

    if not isinstance(resume_value, dict) or not supplied:
        outcome = "cancelled"
    elif any_group_conflicting:
        outcome = "conflicting"
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
        expected_description = planning.get("selected_description")
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

        # A satisfied (or conflicting) group's OTHER, unanswered member(s)
        # are not "still missing" — the group as a whole is no longer
        # awaiting an answer once at least one member is accepted, whether
        # that turns out to be exactly one (satisfied) or more than one
        # (conflicting, see below) — so e.g. supplying only "data" from a
        # path/data group must not still list "path" here.
        accepted_names = set(accepted)
        satisfied_group_members: set[str] = set()
        conflicting_members: set[str] = set()
        for group in field_groups:
            present = group & accepted_names
            if present:
                satisfied_group_members |= group
            if len(present) > 1:
                # ADR-0010 §15: true XOR — reported here immediately (not
                # only via the retry's fresh plan_execution() call) so
                # execution_input_recovery is self-descriptive the moment
                # this node writes it, consistent with "invalid"/
                # "still_missing" already being computed here rather than
                # deferred.
                conflicting_members |= present
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
            "expected_description": expected_description,
            "expected_input_schema": expected_schema,
            "expected_input_field_groups": expected_groups,
            "requested": requested,
            "accepted": sorted(accepted.keys()),
            "still_missing": still_missing,
            "conflicting": sorted(conflicting_members),
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


def _capture_execution_pin(
    execution_registry: ExecutionBindingRegistry, skill_id: str
) -> Optional[dict[str, Any]]:
    """
    The execution pin for `skill_id` (ADR-0003 section 10.2), captured from the
    live registry - the ONLY place the graph reads it for pinning. `None` means
    no binding was registered. A binding that cannot be pinned (non-JSON-native
    default, ADR-0003 section 10.4) yields a deliberately MALFORMED marker, so
    it fails closed as `execution_pin_malformed`: never approved, never run.
    """
    try:
        return execution_registry.pin(skill_id)
    except ValueError as exc:
        return {"unpinnable": str(exc)}


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
            caller_update: dict[str, Any] = {
                "steps": _append_step(
                    state, "plan_execution", "caller_supplied_pending_execution_preserved"
                ),
            }
            if "execution_pin" not in existing_pending:
                # ADR-0003 section 10.6: pinned at FIRST OBSERVATION, before
                # any approval interrupt, from the live registry; a later
                # visit of this node finds the key and never re-pins. (An
                # explicit None is "no binding at capture" and is kept.)
                caller_update["pending_execution"] = {
                    **existing_pending,
                    "execution_pin": _capture_execution_pin(
                        execution_registry, str(existing_pending.get("skill_id"))
                    ),
                }
            return caller_update

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
        # candidate_choice (ADR-0010 §16, Q18): a validated human choice
        # among a prior ambiguous_candidates round's own candidates, or
        # None on a first pass / when there was never any ambiguity — see
        # plan_execution()'s own docstring for what it does with either.
        candidate_choice = state.get("candidate_choice")
        result = plan_execution(
            analysis,
            execution_registry,
            available_inputs=available_inputs,
            selected_skill_id=candidate_choice,
        )

        # Gated on terminal is None (not just attempted is True): once a
        # recovery round is finalized below, a LATER retry of this same
        # node (e.g. candidate disambiguation resolves ambiguity, then a
        # separate provide_execution_inputs round follows for the now-
        # unambiguous candidate) must not re-finalize an already-finalized
        # round a second time — each of the two recovery kinds below is
        # finalized at most once, independently.
        candidate_recovery = state.get("candidate_selection")
        candidate_unfinalized = (
            candidate_recovery is not None
            and candidate_recovery.get("attempted") is True
            and candidate_recovery.get("terminal") is None
        )
        recovery = state.get("execution_input_recovery")
        execution_unfinalized = (
            recovery is not None
            and recovery.get("attempted") is True
            and recovery.get("terminal") is None
        )

        updated_candidate_recovery: Optional[dict[str, Any]] = None
        updated_recovery: Optional[dict[str, Any]] = None
        plan_allowed = result.status == "planned"

        if candidate_unfinalized:
            # Retry after a choose_candidate interrupt resumed (ADR-0010
            # §16). This is the ONLY place a candidate_choice's validity
            # against the *current* registry is confirmed — the interrupt
            # node's own "selected" classification only proves the choice
            # matched what was offered at ask time, never that it still
            # resolves anything now (the registry could have changed
            # underneath the pause, e.g. a binding deregistered).
            assert candidate_recovery is not None
            raw_candidate_outcome: Any = candidate_recovery.get("outcome")
            candidate_final_outcome: str
            candidate_terminal: bool
            candidate_detail: Optional[str] = None
            # The description is compared against the CURRENT registry
            # binding here (this is the authoritative retry, not pre-
            # interrupt code, so a live lookup is correct and required —
            # the replay-safety rule only forbids live reads before
            # interrupt()). binding_id comes from the fresh PlanningResult.
            live_binding = execution_registry.get_binding(
                str(candidate_recovery.get("chosen_skill_id"))
            )
            if raw_candidate_outcome != "selected":
                candidate_final_outcome, candidate_terminal = raw_candidate_outcome, True
            elif result.selected_skill_id == candidate_recovery.get(
                "chosen_skill_id"
            ) and (
                result.selected_binding_id != candidate_recovery.get("expected_binding_id")
                or live_binding is None
                or live_binding.description != candidate_recovery.get("expected_description")
            ):
                # Same skill_id, but NOT the binding the human was shown
                # (audit finding D1): re-registered under a new binding_id
                # (different runtime/behavior), or the same binding_id with
                # a different description, during the pause. Planning or
                # executing whatever is registered now under the human's
                # earlier choice would run something they never saw.
                candidate_final_outcome, candidate_terminal = "candidate_mismatch", True
                candidate_detail = (
                    "binding_changed"
                    if result.selected_binding_id != candidate_recovery.get("expected_binding_id")
                    else "description_changed"
                )
            elif result.selected_skill_id != candidate_recovery.get("chosen_skill_id"):
                # The fresh, authoritative call did not resolve to the skill
                # the human actually chose. Covers: still "ambiguous_
                # candidates" (choice no longer a candidate); AND the subtler
                # case where the chosen skill's binding was deregistered
                # during the pause, leaving only the OTHER candidate —
                # plan_execution() then sees a single candidate and would
                # happily plan *that* one. Silently executing a skill the
                # human never chose is exactly what `[P§35]` forbids, so
                # ANY resolution other than the chosen skill_id is a
                # mismatch (never "ask again"; this interrupt is one shot).
                # selected_skill_id is None for no_executable_candidate/
                # ambiguous_candidates, so those are covered too.
                candidate_final_outcome, candidate_terminal = "candidate_mismatch", True
                candidate_detail = "skill_not_resolved"
            else:
                candidate_final_outcome, candidate_terminal = "selected", False

            updated_candidate_recovery = {
                **candidate_recovery,
                "outcome": candidate_final_outcome,
                "terminal": candidate_terminal,
                "mismatch_detail": candidate_detail,
            }
            if candidate_terminal:
                plan_allowed = False

        elif execution_unfinalized:
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
            # ADR-0010 section 17 (issue #43): strict description pinning
            # through input recovery. "Nothing to compare" never counts as
            # "unchanged" - a record without expected_description, or a fresh
            # result without selected_description, fails closed.
            expected_description = recovery.get("expected_description")
            description_ok = (
                isinstance(expected_description, str)
                and result.selected_description == expected_description
            )
            raw_outcome: Any = recovery.get("outcome")

            final_outcome: str
            terminal: bool
            detail: Optional[str]
            if not identity_ok:
                final_outcome, terminal, detail = "binding_mismatch", True, "identity_changed"
            elif not schema_ok:
                final_outcome, terminal, detail = "binding_mismatch", True, "schema_changed"
            elif not description_ok:
                final_outcome, terminal, detail = "binding_mismatch", True, "description_changed"
            elif raw_outcome != "supplied":
                final_outcome, terminal, detail = raw_outcome, True, None
            elif result.status == "conflicting_inputs":
                # ADR-0010 §15: reachable even when the interrupt node's own
                # `_classify_execution_input_resume()` call reported
                # "supplied" — that check only inspects the group(s) THIS
                # round's `field_groups` reconstructed (groups fully absent
                # from `requested`, i.e. still unsatisfied at plan time). A
                # resume payload may legally include a declared name beyond
                # what was actually asked (accepted, not rejected, by that
                # function); if it names the OTHER member of a group already
                # satisfied by a prior round's `execution_inputs`, the
                # per-round check has no visibility into that — only this
                # retry's fresh, authoritative plan_execution() call, run
                # against the fully merged execution_inputs, can catch it.
                # Labeled precisely rather than folded into the generic
                # "still_incomplete_after_supply" guard below, so a human
                # who over-answers sees "conflicting," not a misleading
                # "binding mismatch."
                final_outcome, terminal, detail = (
                    "conflicting",
                    True,
                    "conflicting_inputs_supplied",
                )
            elif result.status != "planned":
                # Invariant/safety guard, not a reachable branch under
                # normal operation (verified on PR #33 review, extended for
                # field groups in ADR-0010 §14/§15): if identity_ok and
                # schema_ok both hold, every requested name is, by
                # construction, either a required field or a member of a
                # group of the (unchanged) selected binding, and the
                # interrupt node's own "supplied" classification already
                # means every individually-required name — and exactly one
                # member of every group it saw — has a valid value in the
                # now-merged execution_inputs; the branch above handles the
                # one known way `result.status` can still be
                # "conflicting_inputs" here, so plan_execution()'s own
                # missing-field/group check (ADR-0010 §3/§14/§15) cannot
                # find anything else unsatisfied, and result.status must be
                # "planned". This branch exists only
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
                "execution_pin": _capture_execution_pin(
                    execution_registry, result.plan.skill_id
                ),
            }
            log_extra["skill_id"] = result.plan.skill_id
            log_extra["task_component"] = result.plan.task_component
        elif result.status == "ambiguous_candidates":
            log_extra["candidate_skill_ids"] = list(result.candidate_skill_ids)
        elif result.status == "missing_required_inputs":
            log_extra["missing_inputs"] = list(result.missing_inputs)
        elif result.status == "conflicting_inputs":
            log_extra["conflicting_inputs"] = list(result.conflicting_inputs)

        if updated_candidate_recovery is not None:
            log_extra["candidate_outcome"] = updated_candidate_recovery["outcome"]
            log_extra["candidate_terminal"] = updated_candidate_recovery["terminal"]
        if updated_recovery is not None:
            log_extra["recovery_outcome"] = updated_recovery["outcome"]
            log_extra["recovery_terminal"] = updated_recovery["terminal"]

        planning_dict = dataclasses.asdict(result)
        recovery_terminal_now = bool(
            (updated_candidate_recovery and updated_candidate_recovery["terminal"])
            or (updated_recovery and updated_recovery["terminal"])
        )
        if recovery_terminal_now:
            # Audit finding D3: a recovery round that finalized as a terminal
            # failure means this run has NO executable intent, yet the fresh
            # plan_execution() call above may still have produced a "planned"
            # PlanningResult — e.g. for the OTHER candidate after the chosen
            # skill vanished (candidate_mismatch), or for a swapped binding
            # (binding_mismatch, ADR-0010 §13). Leaving that plan in
            # `planning_result` would let a downstream reader mistake a plan
            # for a skill/binding the human never chose or was never asked
            # about for executable intent. So `plan` is cleared; `status`,
            # the candidate/selected_* fields, and everything else stay as
            # diagnostics of what the fresh call actually resolved (they
            # describe planning's result, not intent — the recovery record
            # and `pending_execution is None` are the authority on that).
            planning_dict["plan"] = None

        update: dict[str, Any] = {
            "pending_execution": pending,
            "planning_result": planning_dict,
            "steps": _append_step(state, "plan_execution", "planning_attempted", **log_extra),
        }
        if updated_candidate_recovery is not None:
            update["candidate_selection"] = updated_candidate_recovery
            if updated_candidate_recovery["terminal"]:
                # Same reasoning as execution_input_recovery's own terminal
                # handling below — this node's own conditional edge
                # (_route_after_planning) sends a terminal candidate
                # recovery outcome straight to END, bypassing approval_gate
                # entirely, so it must set status="done" itself.
                update["status"] = "done"
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

    # Candidate disambiguation (ADR-0010 §16, Q18) is checked FIRST —
    # architecturally, plan_execution() cannot even determine input
    # completeness (missing/conflicting) until exactly one candidate is
    # selected, so an unresolved ambiguity always takes priority over the
    # execution-input recovery checks below.
    candidate_recovery = state.get("candidate_selection")
    candidate_already_attempted = (
        candidate_recovery is not None and candidate_recovery.get("attempted") is True
    )

    if planning.get("status") == "ambiguous_candidates" and not candidate_already_attempted:
        return "choose_candidate"

    if candidate_already_attempted and candidate_recovery is not None:
        if candidate_recovery.get("terminal"):
            # A failed/invalid/cancelled/mismatched disambiguation is
            # terminal — bypasses approval_gate entirely, same "never read
            # as approval not required for a plan never produced" rule
            # execution_input_recovery's own terminal check already
            # documents. Never a second choose_candidate interrupt.
            return END
        # Otherwise: the choice succeeded (terminal is False) — fall
        # through to the ordinary missing/conflicting/planned routing
        # below, evaluated against `planning`, which already reflects the
        # FRESH plan_execution() call this same node retry made for the
        # now-unambiguous candidate.

    recovery = state.get("execution_input_recovery")
    already_attempted = recovery is not None and recovery.get("attempted") is True

    if planning.get("status") == "missing_required_inputs" and not already_attempted:
        return "provide_execution_inputs"

    if already_attempted:
        # A recovery round just finalized (or this pass is the retry that
        # follows one). terminal is the single, authoritative signal — an
        # incomplete/invalid/cancelled/conflicting/binding_mismatch outcome
        # bypasses approval_gate entirely, so a failed recovery can never
        # be read as "approval not required" for a plan that was never
        # produced.
        assert recovery is not None
        return END if recovery.get("terminal") else "approval_gate"

    # First-pass planned / no_executable_candidate / ambiguous_candidates /
    # conflicting_inputs (ADR-0010 §15: a true XOR violation, caught before
    # any plan is ever produced) — approval_gate no-ops for all of these
    # except "planned" (no pending_execution was set, so it sets
    # approval_decision="not_required"/status="done" without interrupting
    # or executing anything) — unchanged from before ADR-0010 §13/§15.
    return "approval_gate"


_MISSING_PIN: Any = object()
"""Sentinel: the `execution_pin` key is absent (distinct from an explicit None)."""


def _pin_evidence(pin: Any) -> ExecutionEvidence:
    """binding_id/runtime_id read defensively from a pin that may be unusable -
    `None`s when it cannot be read, never an exception."""
    binding = pin.get("binding") if isinstance(pin, dict) else None
    if isinstance(binding, dict):
        binding_id, runtime_id = binding.get("binding_id"), binding.get("runtime_id")
        if isinstance(binding_id, str) and isinstance(runtime_id, str):
            return ExecutionEvidence(binding_id, runtime_id, None, None)
    return ExecutionEvidence(None, None, None, None)


def _make_approval_gate_node(executor: SkillExecutor):
    # `executor` is kept in the signature for the graph builder, but the gate
    # no longer reads it: ADR-0003 section 10.2 - the gate decides from the
    # checkpointed execution pin only, never a live registry read.
    def _node_approval_gate(state: AgentState) -> dict[str, Any]:
        pending = state.get("pending_execution")
        if pending is None:
            return {
                "approval_decision": "not_required",
                "status": "done",
                "steps": _append_step(state, "approval_gate", "no_pending_execution"),
            }

        skill_id = pending.get("skill_id")
        pin_state: Any = pending.get("execution_pin", _MISSING_PIN)

        # Missing or malformed pin: no interrupt, approval_decision left None
        # (never "not_required" - that would read as "nothing to approve").
        if pin_state is _MISSING_PIN or (
            pin_state is not None and not pin_is_well_formed(pin_state, skill_id=str(skill_id))
        ):
            return {
                "steps": _append_step(
                    state, "approval_gate", "execution_pin_unusable", skill_id=skill_id
                ),
            }

        # Explicit None: no binding at capture, nothing can execute.
        if pin_state is None:
            return {
                "approval_decision": "not_required",
                "steps": _append_step(
                    state, "approval_gate", "approval_not_required", skill_id=skill_id
                ),
            }

        binding_pin = pin_state["binding"]
        if binding_pin["approval_policy"] != "approval_required":
            return {
                "approval_decision": "not_required",
                "steps": _append_step(
                    state, "approval_gate", "approval_not_required", skill_id=skill_id
                ),
            }

        payload = {
            "type": "approval",
            "skill_id": skill_id,
            "binding_id": binding_pin["binding_id"],
            "runtime_id": binding_pin["runtime_id"],
            "description": binding_pin["description"],
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
                skill_id=skill_id,
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
        assert pending is not None  # _route_after_approval only routes here with a plan
        skill_id = pending["skill_id"]
        decision = state.get("approval_decision")

        def _refusal(
            status: Literal["rejected", "not_executable"],
            category: Literal["approval_denied", "no_binding", "binding_mismatch"],
            message: str,
            pin: Any = None,
        ) -> SkillExecutionResult:
            return SkillExecutionResult(
                skill_id=skill_id,
                status=status,
                evidence=_pin_evidence(pin),
                error=ExecutionError(category, message),
            )

        pin = pending.get("execution_pin")
        result: SkillExecutionResult
        # ADR-0003 section 10.6 - ordered checks, rejection FIRST. Nothing
        # before the executor call reads the live registry.
        if decision == "rejected":
            # Invariant R: terminal. No pin validation, no registry read, no
            # executor call - a binding/policy/runtime change has no path here.
            result = _refusal(
                "rejected",
                "approval_denied",
                "Execution was rejected by the human at the approval gate.",
                pin,
            )
        elif "execution_pin" not in pending:
            result = _refusal(
                "not_executable",
                "binding_mismatch",
                "integrity check failed: execution_pin_missing",
            )
        elif pin is None:
            result = _refusal(
                "not_executable",
                "no_binding",
                "No execution binding was registered when this execution was "
                "planned; a binding registered afterwards was never approved.",
            )
        elif not pin_is_well_formed(pin, skill_id=str(skill_id)):
            result = _refusal(
                "not_executable",
                "binding_mismatch",
                "integrity check failed: execution_pin_malformed",
                pin,
            )
        elif decision != (
            "approved" if pin["binding"]["approval_policy"] == "approval_required" else "not_required"
        ):
            # Defensive guard (A1): unreachable through the gate. A bare
            # "not_required" (or None) must never run a pinned
            # approval_required binding.
            result = _refusal(
                "not_executable",
                "binding_mismatch",
                "integrity check failed: approval_decision_inconsistent",
                pin,
            )
        else:
            skill = skill_inventory.get(skill_id)
            if skill is None:
                result = _refusal(
                    "not_executable",
                    "no_binding",
                    f"'{skill_id}' was not found by skill discovery.",
                )
            else:
                request = SkillExecutionRequest(
                    inputs=pending.get("inputs", {}),
                    task=pending.get("task"),
                    approved=decision in ("approved", "not_required"),
                    expected_binding_pin=pin,
                )
                result = executor.execute(skill, request)

        update: dict[str, Any] = {
            "execution_result": dataclasses.asdict(result),
            "status": "done",
            "steps": _append_step(
                state, "execute", "execution_attempted", skill_id=skill_id, result_status=result.status
            ),
        }
        if result.status in ("rejected", "not_executable"):
            # Terminal-failure invariant (D3, #42; ADR-0003 section 10.10): a
            # run whose plan did not start must not leave an executable plan
            # in planning_result. pending_execution is kept as the record of
            # what was approved; approval_decision is never rewritten here.
            planning = state.get("planning_result")
            if planning is not None:
                update["planning_result"] = {**planning, "plan": None}
        return update

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
    builder.add_node("choose_candidate", _make_choose_candidate_node())
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
            "choose_candidate": "choose_candidate",
            "provide_execution_inputs": "provide_execution_inputs",
            "approval_gate": "approval_gate",
            END: END,
        },
    )
    builder.add_edge("choose_candidate", "plan_execution")
    builder.add_edge("provide_execution_inputs", "plan_execution")
    builder.add_conditional_edges(
        "approval_gate", _route_after_approval, {"execute": "execute", END: END}
    )
    builder.add_edge("execute", END)

    return builder.compile(checkpointer=checkpointer)
