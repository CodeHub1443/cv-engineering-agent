"""
cv_agent.graph.workflow — Requirements-clarification + approval-gated
execution workflow graph.

See ADR-0003. This is the first LangGraph topology in the repo that uses
real interrupts (`langgraph.types.interrupt`), not the minimal
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
                        clarify   approval_gate
                     (interrupt)       |
                            \\        (pending_execution present
                             \\        and its binding requires
                              \\       approval?)
                               \\    yes /      \\ no / none pending
                                v       v        v
                    analyze_requirements   execute   END
                    (loop back, now with          |
                     clarification_answers        v
                     as assumptions — routes      END
                     straight to approval_gate
                     the second time through)

`clarify` and `approval_gate` are the only two interrupt points. Both use
LangGraph's dynamic `interrupt()` — the node's own call pauses the graph;
resuming with `Command(resume=value)` re-enters that same node with
`interrupt()` returning `value` instead of pausing again. State (including
everything written by nodes that already ran) survives the pause because
the graph is compiled with a checkpointer, keyed by `thread_id`.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Literal, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from cv_agent.execution.executor import SkillExecutor
from cv_agent.execution.models import (
    ExecutionError,
    ExecutionEvidence,
    SkillExecutionRequest,
    SkillExecutionResult,
)
from cv_agent.graph.state import AgentState
from cv_agent.requirements.analyzer import RequirementsAnalyzer
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


def _route_after_analysis(state: AgentState) -> Literal["clarify", "approval_gate"]:
    analysis = state.get("requirements_analysis") or {}
    questions = analysis.get("clarification_questions") or []
    already_answered = bool(state.get("clarification_answers"))
    if questions and not already_answered:
        return "clarify"
    return "approval_gate"


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
    checkpointer: Optional[Any] = None,
) -> Any:
    """
    Build and compile the requirements-clarification + approval-gated
    execution workflow graph.

    Kept separate from `cv_agent.graph.builder.build_graph()` (the minimal
    Step-1 topology) — see ADR-0003 §4. Every collaborator is injected, not
    imported/constructed here, so tests can pass fakes (fake analyzer,
    fake executor with fake bindings) without touching the real skill
    environment or capability registry.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    builder: StateGraph = StateGraph(AgentState)

    builder.add_node("initialize", _node_initialize)
    builder.add_node("analyze_requirements", _make_analyze_requirements_node(requirements_analyzer))
    builder.add_node("clarify", _node_clarify)
    builder.add_node("approval_gate", _make_approval_gate_node(executor))
    builder.add_node("execute", _make_execute_node(executor, skill_inventory))

    builder.add_edge(START, "initialize")
    builder.add_edge("initialize", "analyze_requirements")
    builder.add_conditional_edges(
        "analyze_requirements",
        _route_after_analysis,
        {"clarify": "clarify", "approval_gate": "approval_gate"},
    )
    builder.add_conditional_edges(
        "clarify", _route_after_clarify, {"analyze_requirements": "analyze_requirements"}
    )
    builder.add_conditional_edges(
        "approval_gate", _route_after_approval, {"execute": "execute", END: END}
    )
    builder.add_edge("execute", END)

    return builder.compile(checkpointer=checkpointer)
