"""
Tests for cv_agent.graph.workflow — the requirements-clarification,
planning, and approval-gated execution interrupt/resume graph
(ADR-0003, ADR-0010).

Uses the real RequirementsAnalyzer/TaskResolver (against an isolated empty
skill root + the real spec/capability_registry.json, same convention as
test_requirements.py) so clarification questions are genuine, plus fake
execution bindings/runtimes (same convention as test_execution.py) so no
real skill runtime is ever touched.

TestPlanExecutionIntegration uses its own self-contained fixtures (a
SkillInventory with is_executable actually wired to a real SkillExecutor,
mirroring CVAgent.__init__'s own wiring) rather than the shared
skill_inventory/task_resolver/analyzer/graph fixtures above, which
deliberately have no is_executable predicate wired in and are relied on
unmodified by every pre-existing test in this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from cv_agent.capabilities.registry import CapabilityRegistry
from cv_agent.execution.binding import ExecutionBinding, ExecutionBindingRegistry, InputField
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
    analyzer: RequirementsAnalyzer,
    executor: SkillExecutor,
    skill_inventory: SkillInventory,
    execution_registry: ExecutionBindingRegistry,
):
    return build_requirements_workflow_graph(
        requirements_analyzer=analyzer,
        executor=executor,
        skill_inventory=skill_inventory,
        execution_registry=execution_registry,
        checkpointer=MemorySaver(),
    )


def _start(
    graph,
    task: str,
    session_id: str,
    pending_execution: dict[str, Any] | None = None,
    execution_inputs: dict[str, Any] | None = None,
):
    initial = {
        "session_id": session_id,
        "task": task,
        "steps": [],
        "requirements_analysis": None,
        "clarification_answers": {},
        "execution_inputs": execution_inputs or {},
        "planning_result": None,
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


class TestManuallySuppliedPendingExecutionPrecedence:
    """Uses the pre-existing, unmodified graph/execution_registry/
    skill_inventory fixtures — same setup TestApprovalGate's 8 tests already
    exercise. Makes the precedence rule explicit rather than only proven
    incidentally by those tests continuing to pass."""

    def test_caller_supplied_pending_execution_is_never_overwritten(
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
        execution_registry.register_runtime(
            FakeRuntime(outcome=RuntimeOutcome(success=True, output={}))
        )
        supplied = {"skill_id": "fixture-skill", "inputs": {"a": 1}, "task": "t"}

        result = _start(graph, _WELL_DEFINED_TASK, "precedence-1", pending_execution=supplied)

        assert result["pending_execution"]["skill_id"] == "fixture-skill"
        assert result["pending_execution"]["inputs"] == {"a": 1}
        plan_step = next(s for s in result["steps"] if s["node"] == "plan_execution")
        assert plan_step["action"] == "caller_supplied_pending_execution_preserved"
        # ADR-0010 §10: no plan_execution() call was made, so there is no
        # PlanningResult to report — planning_result stays None, never an
        # ad-hoc "skipped" placeholder.
        assert result["planning_result"] is None

    def test_execution_inputs_are_ignored_when_pending_execution_is_supplied(
        self, graph, skill_inventory: SkillInventory, execution_registry: ExecutionBindingRegistry
    ) -> None:
        """ADR-0010 §12: a caller-supplied pending_execution still takes
        full precedence even when execution_inputs is also supplied —
        plan_execution() is never called, so execution_inputs is simply
        unused for this run, not merged into the caller's own plan."""
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
        execution_registry.register_runtime(
            FakeRuntime(outcome=RuntimeOutcome(success=True, output={}))
        )
        supplied = {"skill_id": "fixture-skill", "inputs": {"a": 1}, "task": "t"}

        result = _start(
            graph,
            _WELL_DEFINED_TASK,
            "precedence-2",
            pending_execution=supplied,
            execution_inputs={"path": "/should/be/ignored"},
        )

        assert result["pending_execution"]["inputs"] == {"a": 1}
        plan_step = next(s for s in result["steps"] if s["node"] == "plan_execution")
        assert plan_step["action"] == "caller_supplied_pending_execution_preserved"
        assert result["planning_result"] is None


_PLANNING_TASK = (
    "Detect intruders using our 8 outdoor CCTV cameras at 1080p/15fps, "
    "deploy on a Jetson Orin, need real-time response with recall above 95%, "
    "and we have 2000 labeled clips already. Also evaluate deployment "
    "optimization performance benchmarking of the model."
)
"""Deliberately as fully-specified as _WELL_DEFINED_TASK (zero clarification
questions — verified empirically) plus benchmarking/deployment-optimization
vocabulary, so TestPlanExecutionIntegration's tests reach plan_execution
directly without an intervening clarification interrupt, matching this
module's own is_executable-wired fixture skills under task_component
"person_detection"."""
_PLANNING_SKILL_DESCRIPTION = "TensorRT performance benchmarking and layer analysis tool."

_VAGUE_PLANNING_TASK = (
    "Detect escape attempts. Also evaluate deployment optimization "
    "performance benchmarking of the model."
)
"""Deliberately missing environment/camera/deployment-target/latency/
accuracy/data-availability fields (unlike _PLANNING_TASK) so it interrupts
for clarification first — but keeps the same person_detection trigger
("escape"/"detect") and benchmarking vocabulary _PLANNING_TASK already
proves matches the fixture skill, so plan_execution still finds the same
candidate once clarification resolves."""


def _write_planning_skill(root: Path, skill_id: str) -> None:
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill_id}\ndescription: {_PLANNING_SKILL_DESCRIPTION}\n---\n",
        encoding="utf-8",
    )


class TestPlanExecutionIntegration:
    """
    ADR-0010 §9: plan_execution() wired into build_requirements_workflow_graph()
    as a new node, positioned between analyze_requirements/clarify and
    approval_gate. Every test here builds its own graph against a real,
    tmp_path-discovered skill and a real SkillExecutor-backed
    is_executable predicate — proving the actual skill_links ->
    pending_execution path end to end, not a mocked shortcut.
    """

    def _graph_for(
        self,
        tmp_path: Path,
        execution_registry: ExecutionBindingRegistry,
        *,
        skill_ids: tuple[str, ...],
    ):
        for skill_id in skill_ids:
            _write_planning_skill(tmp_path, skill_id)
        executor = SkillExecutor(execution_registry)
        skill_inventory = SkillInventory(
            sources=(LocalSkillSource(roots=(tmp_path,)),),
            is_executable=executor.can_execute,
        )
        registry = CapabilityRegistry(_REGISTRY_PATH)
        registry.load()
        task_resolver = TaskResolver(capability_registry=registry, skill_inventory=skill_inventory)
        analyzer = RequirementsAnalyzer(task_resolver=task_resolver, llm=None)
        return build_requirements_workflow_graph(
            requirements_analyzer=analyzer,
            executor=executor,
            skill_inventory=skill_inventory,
            execution_registry=execution_registry,
            checkpointer=MemorySaver(),
        )

    @staticmethod
    def _register(
        execution_registry: ExecutionBindingRegistry,
        skill_id: str,
        *,
        approval_policy: str = "allowed",
        input_schema: tuple[InputField, ...] = (),
    ) -> "FakeRuntime":
        # A distinct runtime_id per skill_id — registering two bindings that
        # both default to "fake-runtime" would silently overwrite one
        # FakeRuntime's registration with the other's in the registry.
        rt = FakeRuntime(
            runtime_id=f"fake-runtime-{skill_id}",
            outcome=RuntimeOutcome(success=True, output={"ok": True}),
        )
        execution_registry.register_runtime(rt)
        execution_registry.register_binding(
            ExecutionBinding(
                skill_id=skill_id,
                binding_id=f"{skill_id}-v1",
                runtime_id=rt.runtime_id,
                approval_policy=approval_policy,  # type: ignore[arg-type]
                verified=True,
                input_schema=input_schema,
            )
        )
        return rt

    def test_one_executable_candidate_populates_pending_execution(
        self, tmp_path: Path
    ) -> None:
        execution_registry = ExecutionBindingRegistry()
        self._register(execution_registry, "trt-perf-analysis")
        graph = self._graph_for(
            tmp_path, execution_registry, skill_ids=("trt-perf-analysis",)
        )

        result = _start(graph, _PLANNING_TASK, "plan-1")

        assert "__interrupt__" not in result
        assert result["pending_execution"] == {
            "skill_id": "trt-perf-analysis",
            "inputs": {},
            "task": _PLANNING_TASK,
        }
        plan_step = next(s for s in result["steps"] if s["node"] == "plan_execution")
        assert plan_step["planning_status"] == "planned"
        assert plan_step["skill_id"] == "trt-perf-analysis"
        assert plan_step["task_component"] == "person_detection"
        # ADR-0010 §10: the same outcome is now a structured, top-level
        # state field too, not only recoverable by parsing steps.
        # WARNING: this strict dict equality (including the literal `()`
        # tuples below) only holds on a fresh, non-checkpoint-restored
        # invoke — ADR-0004's own CVAgent._sync_memory_after_run() docstring
        # already documents that AgentState's tuple fields come back as
        # lists after a checkpoint round-trip (e.g. after a resume, not
        # exercised in this test). Do not copy this exact pattern to assert
        # on post-resume state — normalize with list(...)/sorted(...)
        # instead, as the ambiguous/missing-input tests below already do.
        assert result["planning_result"] == {
            "status": "planned",
            "plan": {
                "skill_id": "trt-perf-analysis",
                "task_component": "person_detection",
                "inputs": {},
                "source_task": _PLANNING_TASK,
            },
            "candidate_skill_ids": (),
            "missing_inputs": (),
        }

    def test_no_executable_candidate_reaches_end_without_execution(
        self, tmp_path: Path
    ) -> None:
        execution_registry = ExecutionBindingRegistry()
        # Skill is discovered but no binding is ever registered for it.
        graph = self._graph_for(
            tmp_path, execution_registry, skill_ids=("trt-perf-analysis",)
        )

        result = _start(graph, _PLANNING_TASK, "plan-2")

        assert "__interrupt__" not in result
        assert result["pending_execution"] is None
        assert result["execution_result"] is None
        assert result["status"] == "done"
        assert "execute" not in [s["node"] for s in result["steps"]]
        plan_step = next(s for s in result["steps"] if s["node"] == "plan_execution")
        assert plan_step["planning_status"] == "no_executable_candidate"
        assert result["planning_result"]["status"] == "no_executable_candidate"
        assert result["planning_result"]["plan"] is None

    def test_multiple_executable_candidates_are_ambiguous_no_execution(
        self, tmp_path: Path
    ) -> None:
        execution_registry = ExecutionBindingRegistry()
        self._register(execution_registry, "trt-perf-analysis")
        self._register(execution_registry, "bench-tool-b")
        graph = self._graph_for(
            tmp_path, execution_registry, skill_ids=("trt-perf-analysis", "bench-tool-b")
        )

        result = _start(graph, _PLANNING_TASK, "plan-3")

        assert result["pending_execution"] is None
        assert result["execution_result"] is None
        plan_step = next(s for s in result["steps"] if s["node"] == "plan_execution")
        assert plan_step["planning_status"] == "ambiguous_candidates"
        assert sorted(plan_step["candidate_skill_ids"]) == ["bench-tool-b", "trt-perf-analysis"]
        assert result["planning_result"]["status"] == "ambiguous_candidates"
        assert result["planning_result"]["plan"] is None
        assert sorted(result["planning_result"]["candidate_skill_ids"]) == [
            "bench-tool-b",
            "trt-perf-analysis",
        ]

    def test_missing_required_input_no_plan_no_execution(self, tmp_path: Path) -> None:
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=(InputField(name="path", required=True, description="folder path"),),
        )
        graph = self._graph_for(
            tmp_path, execution_registry, skill_ids=("trt-perf-analysis",)
        )

        result = _start(graph, _PLANNING_TASK, "plan-4")

        assert result["pending_execution"] is None
        assert result["execution_result"] is None
        plan_step = next(s for s in result["steps"] if s["node"] == "plan_execution")
        assert plan_step["planning_status"] == "missing_required_inputs"
        assert plan_step["missing_inputs"] == ["path"]
        assert result["planning_result"]["status"] == "missing_required_inputs"
        assert result["planning_result"]["plan"] is None
        assert list(result["planning_result"]["missing_inputs"]) == ["path"]

    def test_execution_inputs_satisfy_missing_required_input_and_produce_a_plan(
        self, tmp_path: Path
    ) -> None:
        """ADR-0010 §12: a caller-supplied execution_inputs value, keyed by
        InputField.name, is what turns the exact same binding that produced
        missing_required_inputs above into a real plan — same fixture,
        same required field, only start_workflow's new parameter differs."""
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=(InputField(name="path", required=True, description="folder path"),),
        )
        graph = self._graph_for(
            tmp_path, execution_registry, skill_ids=("trt-perf-analysis",)
        )

        result = _start(
            graph,
            _PLANNING_TASK,
            "plan-4b",
            execution_inputs={"path": "/data/clips"},
        )

        assert result["pending_execution"] == {
            "skill_id": "trt-perf-analysis",
            "inputs": {"path": "/data/clips"},
            "task": _PLANNING_TASK,
        }
        assert result["planning_result"]["status"] == "planned"
        assert result["planning_result"]["plan"]["inputs"] == {"path": "/data/clips"}

    def test_execution_inputs_survive_the_clarification_loop(self, tmp_path: Path) -> None:
        """execution_inputs supplied at start_workflow() must reach
        plan_execution unchanged even when a clarification interrupt/resume
        happens first — no node between initialize and plan_execution may
        touch it, and clarification_answers must never be folded into it."""
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=(InputField(name="path", required=True, description="folder path"),),
        )
        graph = self._graph_for(
            tmp_path, execution_registry, skill_ids=("trt-perf-analysis",)
        )

        started = _start(
            graph,
            _VAGUE_PLANNING_TASK,
            "plan-9",
            execution_inputs={"path": "/data/clips"},
        )
        assert "__interrupt__" in started
        assert started["__interrupt__"][0].value["type"] == "clarification"

        questions = started["__interrupt__"][0].value["questions"]
        answers = {q["relates_to_field"]: "answered" for q in questions}
        resumed = _resume(graph, "plan-9", answers)

        # clarification_answers is populated (a different namespace) but
        # execution_inputs — never touched by any node — is what actually
        # reaches the plan, unchanged.
        assert resumed["clarification_answers"] == answers
        assert resumed["planning_result"]["status"] == "planned"
        assert resumed["pending_execution"] == {
            "skill_id": "trt-perf-analysis",
            "inputs": {"path": "/data/clips"},
            "task": _VAGUE_PLANNING_TASK,
        }

    def test_planned_execution_passes_through_approval_gate(self, tmp_path: Path) -> None:
        execution_registry = ExecutionBindingRegistry()
        runtime = self._register(
            execution_registry, "trt-perf-analysis", approval_policy="approval_required"
        )
        graph = self._graph_for(
            tmp_path, execution_registry, skill_ids=("trt-perf-analysis",)
        )

        result = _start(graph, _PLANNING_TASK, "plan-5")

        assert "__interrupt__" in result
        payload = result["__interrupt__"][0].value
        assert payload["type"] == "approval"
        assert payload["skill_id"] == "trt-perf-analysis"
        assert runtime.calls == []

    def test_approved_planned_execution_reaches_the_executor(self, tmp_path: Path) -> None:
        execution_registry = ExecutionBindingRegistry()
        runtime = self._register(
            execution_registry, "trt-perf-analysis", approval_policy="approval_required"
        )
        graph = self._graph_for(
            tmp_path, execution_registry, skill_ids=("trt-perf-analysis",)
        )

        _start(graph, _PLANNING_TASK, "plan-6")
        resumed = _resume(graph, "plan-6", "approved")

        assert resumed["status"] == "done"
        assert resumed["approval_decision"] == "approved"
        assert resumed["execution_result"]["status"] == "completed"
        assert runtime.calls == [("trt-perf-analysis", {})]

    def test_rejected_planned_execution_never_reaches_the_executor(
        self, tmp_path: Path
    ) -> None:
        """Planning must never weaken the approval gate: a planned,
        approval_required execution that is rejected must behave exactly
        like a manually-supplied one already does (TestApprovalGate)."""
        execution_registry = ExecutionBindingRegistry()
        runtime = self._register(
            execution_registry, "trt-perf-analysis", approval_policy="approval_required"
        )
        graph = self._graph_for(
            tmp_path, execution_registry, skill_ids=("trt-perf-analysis",)
        )

        _start(graph, _PLANNING_TASK, "plan-7")
        resumed = _resume(graph, "plan-7", "rejected")

        assert resumed["approval_decision"] == "rejected"
        assert resumed["execution_result"]["status"] == "rejected"
        assert runtime.calls == []

    def test_planning_happens_only_after_clarification_completes(
        self, tmp_path: Path
    ) -> None:
        execution_registry = ExecutionBindingRegistry()
        # Deliberately no skill/binding at all — this test only needs to
        # prove *when* plan_execution runs, not what it decides.
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=())

        started = _start(graph, _VAGUE_TASK, "plan-8")

        assert started["__interrupt__"][0].value["type"] == "clarification"
        assert "plan_execution" not in [s["node"] for s in started["steps"]]
        assert started["planning_result"] is None

        questions = started["__interrupt__"][0].value["questions"]
        answers = {q["relates_to_field"]: "answered" for q in questions}
        resumed = _resume(graph, "plan-8", answers)

        assert "plan_execution" in [s["node"] for s in resumed["steps"]]
        assert resumed["pending_execution"] is None  # nothing was ever registered
        assert resumed["planning_result"]["status"] == "no_executable_candidate"

    def test_planning_result_persists_unchanged_across_an_approval_resume(
        self, tmp_path: Path
    ) -> None:
        """A caller resuming the approval interrupt re-enters approval_gate
        only (LangGraph's dynamic interrupt() semantics, ADR-0003 §1) —
        plan_execution never re-runs, so the *complete* planning_result it
        already wrote (status, full plan, candidate_skill_ids,
        missing_inputs) must survive semantically unchanged through the
        resume, even though the checkpoint round-trip a resume goes through
        may turn its tuple fields into lists (ADR-0004's documented
        instability) — list(...) normalizes both sides before comparing so
        this checks semantic equality, not literal container-type equality.
        """
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry, "trt-perf-analysis", approval_policy="approval_required"
        )
        graph = self._graph_for(
            tmp_path, execution_registry, skill_ids=("trt-perf-analysis",)
        )

        def _normalized(state: dict) -> dict:
            pr = state["planning_result"]
            return {
                "status": pr["status"],
                "plan": pr["plan"],
                "candidate_skill_ids": list(pr["candidate_skill_ids"]),
                "missing_inputs": list(pr["missing_inputs"]),
            }

        started = _start(graph, _PLANNING_TASK, "plan-9")
        before = _normalized(started)
        assert before == {
            "status": "planned",
            "plan": {
                "skill_id": "trt-perf-analysis",
                "task_component": "person_detection",
                "inputs": {},
                "source_task": _PLANNING_TASK,
            },
            "candidate_skill_ids": [],
            "missing_inputs": [],
        }

        resumed = _resume(graph, "plan-9", "approved")
        after = _normalized(resumed)

        assert after == before
