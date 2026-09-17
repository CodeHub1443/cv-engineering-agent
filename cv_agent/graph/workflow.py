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
                     and none answered yet this run?)
                        yes  /        \\  no
                            v          v
                        clarify   plan_execution
                     (interrupt)       |
                            \\        (ADR-0010 §3: caller-supplied
                             \\        pending_execution preserved as-is;
                              \\       otherwise derived from
                               \\      requirements_analysis.skill_links —
                                \\     never overwrites an explicit value)
                                 v
                    analyze_requirements   approval_gate
                    (loop back, now with          |
                     clarification_answers   (pending_execution present
                     as assumptions — routes  and its binding requires
                     straight to               approval?)
                     plan_execution the           yes /      \\ no / none pending
                     second time through)            v        v
                                              execute   END
                                                  |
                                                  v
                                                 END

`clarify` and `approval_gate` are the only two interrupt points.
`plan_execution` never interrupts (ADR-0010 §3: a missing-input interrupt is
explicitly deferred, not built here) and never executes/approves anything —
it only derives `pending_execution` when the caller hasn't already supplied
one. Both interrupt nodes use LangGraph's dynamic `interrupt()` — the node's
own call pauses the graph; resuming with `Command(resume=value)` re-enters
that same node with `interrupt()` returning `value` instead of pausing
again. State (including everything written by nodes that already ran)
survives the pause because the graph is compiled with a checkpointer, keyed
by `thread_id`.
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
    already_answered = bool(state.get("clarification_answers"))
    if questions and not already_answered:
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
    # is treated as "no answers supplied", not fabricated.
    answers_dict: dict[str, str] = dict(answers) if answers else {}

    return {
        "clarification_answers": answers_dict,
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
    # "clarify" a second time because clarification_answers is now set —
    # this prevents an infinite interrupt loop even if unknowns remain.
    return "analyze_requirements"


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
        # available_inputs: currently nothing in AgentState legitimately
        # represents "explicit execution inputs a human has already
        # supplied ahead of planning" — clarification_answers is keyed by
        # RequirementField.name (e.g. "deployment_target"), not by
        # InputField.name (e.g. "path"), and treating it as such would be
        # exactly the "infer execution inputs from arbitrary text" this
        # node must not do (ADR-0010 §3). Honestly passing {} here, not
        # inventing a new state field for this integration step — see
        # docs/state/OPEN_QUESTIONS.md Q17 for the still-open follow-up.
        result = plan_execution(analysis, execution_registry, available_inputs={})

        pending: Optional[dict[str, Any]] = None
        log_extra: dict[str, Any] = {"planning_status": result.status}
        if result.status == "planned":
            assert result.plan is not None
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

        return {
            "pending_execution": pending,
            "planning_result": dataclasses.asdict(result),
            "steps": _append_step(state, "plan_execution", "planning_attempted", **log_extra),
        }

    return _node_plan_execution


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
    builder.add_edge("plan_execution", "approval_gate")
    builder.add_conditional_edges(
        "approval_gate", _route_after_approval, {"execute": "execute", END: END}
    )
    builder.add_edge("execute", END)

    return builder.compile(checkpointer=checkpointer)
