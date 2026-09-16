"""
Tests for cv_agent.graph.workflow — the requirements-clarification and
approval-gated execution interrupt/resume graph (ADR-0003).

Uses the real RequirementsAnalyzer/TaskResolver (against an isolated empty
skill root + the real spec/capability_registry.json, same convention as
test_requirements.py) so clarification questions are genuine, plus fake
execution bindings/runtimes (same convention as test_execution.py) so no
real skill runtime is ever touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from cv_agent.capabilities.registry import CapabilityRegistry
from cv_agent.execution.binding import ExecutionBinding, ExecutionBindingRegistry
from cv_agent.execution.executor import SkillExecutor
from cv_agent.execution.models import RuntimeOutcome
from cv_agent.graph.workflow import build_requirements_workflow_graph
from cv_agent.requirements.analyzer import RequirementsAnalyzer
from cv_agent.skills.inventory import SkillInventory
from cv_agent.skills.local import LocalSkillSource
from cv_agent.skills.models import Skill
from cv_agent.skills.resolver import TaskResolver

_REGISTRY_PATH = Path(__file__).parent.parent / "spec" / "capability_registry.json"

_VAGUE_TASK = "I have a prison project. Escape-attempt detection."

_WELL_DEFINED_TASK = (
    "Detect intruders using our 8 outdoor CCTV cameras at 1080p/15fps, "
    "deploy on a Jetson Orin, need real-time response with recall above 95%, "
    "and we have 2000 labeled clips already."
)


@dataclass
class FakeRuntime:
    runtime_id: str = "fake-runtime"
    outcome: RuntimeOutcome | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def invoke(self, skill, request):
        self.calls.append((skill.skill_id, dict(request.inputs)))
        assert self.outcome is not None
        return self.outcome


@pytest.fixture()
def skill_inventory(tmp_path: Path) -> SkillInventory:
    return SkillInventory(sources=(LocalSkillSource(roots=(tmp_path,)),))


@pytest.fixture()
def task_resolver(skill_inventory: SkillInventory) -> TaskResolver:
    registry = CapabilityRegistry(_REGISTRY_PATH)
    registry.load()
    return TaskResolver(capability_registry=registry, skill_inventory=skill_inventory)


@pytest.fixture()
def analyzer(task_resolver: TaskResolver) -> RequirementsAnalyzer:
    return RequirementsAnalyzer(task_resolver=task_resolver, llm=None)


@pytest.fixture()
def execution_registry() -> ExecutionBindingRegistry:
    return ExecutionBindingRegistry()


@pytest.fixture()
def executor(execution_registry: ExecutionBindingRegistry) -> SkillExecutor:
    return SkillExecutor(execution_registry)


@pytest.fixture()
def graph(
    analyzer: RequirementsAnalyzer, executor: SkillExecutor, skill_inventory: SkillInventory
):
    return build_requirements_workflow_graph(
        requirements_analyzer=analyzer,
        executor=executor,
        skill_inventory=skill_inventory,
        checkpointer=MemorySaver(),
    )


def _start(graph, task: str, session_id: str, pending_execution: dict[str, Any] | None = None):
    initial = {
        "session_id": session_id,
        "task": task,
        "steps": [],
        "requirements_analysis": None,
        "clarification_answers": {},
        "pending_execution": pending_execution,
        "approval_decision": None,
        "execution_result": None,
    }
    cfg = {"configurable": {"thread_id": session_id}}
    return graph.invoke(initial, config=cfg)


def _resume(graph, session_id: str, value: Any):
    cfg = {"configurable": {"thread_id": session_id}}
    return graph.invoke(Command(resume=value), config=cfg)


class TestClarificationInterruptResume:
    def test_graph_pauses_at_clarification_for_a_vague_request(self, graph) -> None:
        result = _start(graph, _VAGUE_TASK, "s1")
        assert "__interrupt__" in result
        payload = result["__interrupt__"][0].value
        assert payload["type"] == "clarification"
        assert len(payload["questions"]) > 0

    def test_state_survives_interruption(self, graph) -> None:
        result = _start(graph, _VAGUE_TASK, "s2")
        assert "__interrupt__" in result
        # Everything analyze_requirements already wrote is present despite
        # the pause — not lost, not reset.
        assert result["requirements_analysis"] is not None
        assert [s["node"] for s in result["steps"]] == ["initialize", "analyze_requirements"]

    def test_no_clarification_interrupt_for_a_fully_specified_request(self, graph) -> None:
        result = _start(graph, _WELL_DEFINED_TASK, "s3")
        # A well-specified request may still have zero unknowns and route
        # straight through to approval_gate/END without ever interrupting.
        assert "__interrupt__" not in result
        assert result["status"] == "done"

    def test_human_answer_is_incorporated_after_resume(self, graph) -> None:
        started = _start(graph, _VAGUE_TASK, "s4")
        questions = started["__interrupt__"][0].value["questions"]
        answers = {q["relates_to_field"]: "answered by human" for q in questions}

        resumed = _resume(graph, "s4", answers)

        assert resumed["clarification_answers"] == answers
        updated_fields = {f["name"]: f["status"] for f in resumed["requirements_analysis"]["fields"]}
        for field_name in answers:
            assert updated_fields[field_name] in ("known", "assumed")

    def test_graph_can_continue_to_completion_after_clarification(self, graph) -> None:
        started = _start(graph, _VAGUE_TASK, "s5")
        questions = started["__interrupt__"][0].value["questions"]
        answers = {q["relates_to_field"]: "answered" for q in questions}

        resumed = _resume(graph, "s5", answers)

        assert "__interrupt__" not in resumed
        assert resumed["status"] == "done"
        assert resumed["steps"][-1]["node"] == "approval_gate"

    def test_clarification_only_interrupts_once_even_if_unknowns_remain(self, graph) -> None:
        started = _start(graph, _VAGUE_TASK, "s6")
        questions = started["__interrupt__"][0].value["questions"]
        # Deliberately answer only one field — unknowns remain, but the
        # graph must not interrupt a second time (infinite-loop guard).
        partial_answers = {questions[0]["relates_to_field"]: "partial answer"}

        resumed = _resume(graph, "s6", partial_answers)

        assert "__interrupt__" not in resumed
        assert resumed["status"] == "done"

    def test_empty_resume_value_produces_no_fabricated_answers(self, graph) -> None:
        """An empty answers dict must never be inflated into fabricated
        field values. (Command(resume=None) itself is unsupported by
        LangGraph's Command API — an empty mapping is the correct way to
        represent 'no answers supplied'.)"""
        _start(graph, _VAGUE_TASK, "s7")
        resumed = _resume(graph, "s7", {})
        assert resumed["clarification_answers"] == {}


class TestApprovalGate:
    def test_approval_required_execution_pauses(
        self, graph, skill_inventory: SkillInventory, execution_registry: ExecutionBindingRegistry
    ) -> None:
        skill_inventory._skills = {"fixture-skill": _fixture_skill()}  # noqa: SLF001
        skill_inventory._loaded = True  # noqa: SLF001
        execution_registry.register_binding(
            ExecutionBinding(
                skill_id="fixture-skill",
                binding_id="b1",
                runtime_id="fake-runtime",
                approval_policy="approval_required",
                verified=True,
            )
        )
        runtime = FakeRuntime(outcome=RuntimeOutcome(success=True, output={}))
        execution_registry.register_runtime(runtime)

        result = _start(
            graph,
            _WELL_DEFINED_TASK,
            "s8",
            pending_execution={"skill_id": "fixture-skill", "inputs": {}, "task": _WELL_DEFINED_TASK},
        )

        assert "__interrupt__" in result
        payload = result["__interrupt__"][0].value
        assert payload["type"] == "approval"
        assert payload["skill_id"] == "fixture-skill"
        assert runtime.calls == []  # no execution occurred before approval

    def test_approval_permits_execution(
        self, graph, skill_inventory: SkillInventory, execution_registry: ExecutionBindingRegistry
    ) -> None:
        skill_inventory._skills = {"fixture-skill": _fixture_skill()}  # noqa: SLF001
        skill_inventory._loaded = True  # noqa: SLF001
        execution_registry.register_binding(
            ExecutionBinding(
                skill_id="fixture-skill",
                binding_id="b1",
                runtime_id="fake-runtime",
                approval_policy="approval_required",
                verified=True,
            )
        )
        runtime = FakeRuntime(outcome=RuntimeOutcome(success=True, output={"ok": True}))
        execution_registry.register_runtime(runtime)

        _start(
            graph,
            _WELL_DEFINED_TASK,
            "s9",
            pending_execution={"skill_id": "fixture-skill", "inputs": {"a": 1}, "task": "t"},
        )
        resumed = _resume(graph, "s9", "approved")

        assert resumed["status"] == "done"
        assert resumed["approval_decision"] == "approved"
        assert resumed["execution_result"]["status"] == "completed"
        assert resumed["execution_result"]["output"] == {"ok": True}
        assert runtime.calls == [("fixture-skill", {"a": 1})]

    def test_rejection_prevents_execution(
        self, graph, skill_inventory: SkillInventory, execution_registry: ExecutionBindingRegistry
    ) -> None:
        skill_inventory._skills = {"fixture-skill": _fixture_skill()}  # noqa: SLF001
        skill_inventory._loaded = True  # noqa: SLF001
        execution_registry.register_binding(
            ExecutionBinding(
                skill_id="fixture-skill",
                binding_id="b1",
                runtime_id="fake-runtime",
                approval_policy="approval_required",
                verified=True,
            )
        )
        runtime = FakeRuntime(outcome=RuntimeOutcome(success=True, output={}))
        execution_registry.register_runtime(runtime)

        _start(
            graph,
            _WELL_DEFINED_TASK,
            "s10",
            pending_execution={"skill_id": "fixture-skill", "inputs": {}, "task": "t"},
        )
        resumed = _resume(graph, "s10", "rejected")

        assert resumed["approval_decision"] == "rejected"
        assert resumed["execution_result"]["status"] == "rejected"
        assert resumed["execution_result"]["error"]["category"] == "approval_denied"
        assert runtime.calls == []  # the runtime must never be invoked

    def test_ambiguous_resume_value_is_treated_as_rejected_not_approved(
        self, graph, skill_inventory: SkillInventory, execution_registry: ExecutionBindingRegistry
    ) -> None:
        """Fail-safe default: only the literal 'approved' string counts as
        approval. Anything else — typos, None, garbage — must reject."""
        skill_inventory._skills = {"fixture-skill": _fixture_skill()}  # noqa: SLF001
        skill_inventory._loaded = True  # noqa: SLF001
        execution_registry.register_binding(
            ExecutionBinding(
                skill_id="fixture-skill",
                binding_id="b1",
                runtime_id="fake-runtime",
                approval_policy="approval_required",
                verified=True,
            )
        )
        runtime = FakeRuntime(outcome=RuntimeOutcome(success=True, output={}))
        execution_registry.register_runtime(runtime)

        _start(
            graph,
            _WELL_DEFINED_TASK,
            "s11",
            pending_execution={"skill_id": "fixture-skill", "inputs": {}, "task": "t"},
        )
        resumed = _resume(graph, "s11", "yes please")

        assert resumed["approval_decision"] == "rejected"
        assert runtime.calls == []

    def test_allowed_policy_executes_without_any_approval_interrupt(
        self, graph, skill_inventory: SkillInventory, execution_registry: ExecutionBindingRegistry
    ) -> None:
        skill_inventory._skills = {"fixture-skill": _fixture_skill()}  # noqa: SLF001
        skill_inventory._loaded = True  # noqa: SLF001
        execution_registry.register_binding(
            ExecutionBinding(
                skill_id="fixture-skill",
                binding_id="b1",
                runtime_id="fake-runtime",
                approval_policy="allowed",
                verified=True,
            )
        )
        runtime = FakeRuntime(outcome=RuntimeOutcome(success=True, output={}))
        execution_registry.register_runtime(runtime)

        result = _start(
            graph,
            _WELL_DEFINED_TASK,
            "s12",
            pending_execution={"skill_id": "fixture-skill", "inputs": {}, "task": "t"},
        )

        assert "__interrupt__" not in result
        assert result["execution_result"]["status"] == "completed"
        assert len(runtime.calls) == 1

    def test_unknown_skill_id_is_not_executable_no_crash(
        self, graph, execution_registry: ExecutionBindingRegistry
    ) -> None:
        result = _start(
            graph,
            _WELL_DEFINED_TASK,
            "s13",
            pending_execution={"skill_id": "never-discovered", "inputs": {}, "task": "t"},
        )
        assert "__interrupt__" not in result
        assert result["execution_result"]["status"] == "not_executable"

    def test_no_pending_execution_skips_execute_node_entirely(self, graph) -> None:
        result = _start(graph, _WELL_DEFINED_TASK, "s14", pending_execution=None)
        assert result["execution_result"] is None
        assert "execute" not in [s["node"] for s in result["steps"]]


def _fixture_skill() -> Skill:
    return Skill(
        skill_id="fixture-skill",
        name="fixture-skill",
        description="A fake test skill.",
        source="fixture",
        location="/fixtures/fixture-skill/SKILL.md",
    )


class TestCVAgentWorkflowWiring:
    """Integration tests through the real CVAgent, not the raw graph — same
    isolation convention as test_skills.py/test_cli.py (CV_AGENT_SKILL_PATHS
    pinned to an empty tmp_path)."""

    def test_start_workflow_pauses_at_clarification(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CV_AGENT_SKILL_PATHS", str(tmp_path))
        from cv_agent.config.settings import AgentConfig
        from cv_agent.runtime.agent import CVAgent

        # Explicit workspace_root (ADR-0004 §1 item 13) — never the real
        # repo cwd. Reuses the same tmp_path already isolating skill_paths.
        agent = CVAgent(AgentConfig(workspace_root=tmp_path))
        result = agent.start_workflow(_VAGUE_TASK, session_id="cva-1")

        assert "__interrupt__" in result

    def test_resume_workflow_incorporates_answers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CV_AGENT_SKILL_PATHS", str(tmp_path))
        from cv_agent.config.settings import AgentConfig
        from cv_agent.runtime.agent import CVAgent

        # Explicit workspace_root (ADR-0004 §1 item 13) — never the real
        # repo cwd. Reuses the same tmp_path already isolating skill_paths.
        agent = CVAgent(AgentConfig(workspace_root=tmp_path))
        started = agent.start_workflow(_VAGUE_TASK, session_id="cva-2")
        questions = started["__interrupt__"][0].value["questions"]
        answers = {q["relates_to_field"]: "provided" for q in questions}

        resumed = agent.resume_workflow("cva-2", answers)

        assert resumed["status"] == "done"
        assert resumed["clarification_answers"] == answers

    def test_get_workflow_state_inspects_without_resuming(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CV_AGENT_SKILL_PATHS", str(tmp_path))
        from cv_agent.config.settings import AgentConfig
        from cv_agent.runtime.agent import CVAgent

        # Explicit workspace_root (ADR-0004 §1 item 13) — never the real
        # repo cwd. Reuses the same tmp_path already isolating skill_paths.
        agent = CVAgent(AgentConfig(workspace_root=tmp_path))
        agent.start_workflow(_VAGUE_TASK, session_id="cva-3")

        state = agent.get_workflow_state("cva-3")

        assert state["requirements_analysis"] is not None
        # Inspecting must not itself resume/advance the paused run.
        state_again = agent.get_workflow_state("cva-3")
        assert state_again["steps"] == state["steps"]

    def test_run_and_health_check_are_unaffected_by_the_new_graph(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pre-existing minimal run()/build_graph() topology must keep
        behaving exactly as before ADR-0003 — proves the two graphs are
        genuinely independent, not a hidden refactor of one into the other."""
        monkeypatch.setenv("CV_AGENT_SKILL_PATHS", str(tmp_path))
        from cv_agent.config.settings import AgentConfig
        from cv_agent.runtime.agent import CVAgent

        # Explicit workspace_root (ADR-0004 §1 item 13) — never the real
        # repo cwd. Reuses the same tmp_path already isolating skill_paths.
        agent = CVAgent(AgentConfig(workspace_root=tmp_path))
        result = agent.run("inspect a model", task_type="model_analysis")

        assert result["status"] == "ready"
        assert result["steps"] == [
            {
                "node": "initialize",
                "action": "session_started",
                "session_id": result["session_id"],
            }
        ]
        assert agent.health_check()["status"] in ("ok", "degraded")
