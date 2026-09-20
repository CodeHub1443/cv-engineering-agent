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
from cv_agent.execution.binding import (
    ExecutionBinding,
    ExecutionBindingRegistry,
    InputField,
    RequiredFieldGroup,
)
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
        "execution_input_recovery": None,
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
        """Declining every clarification question (resume with `""`, the
        correct non-dict falsy sentinel — see the next test for why not
        `{}}`) must never be inflated into fabricated field values, and must
        actually resume the run — not just leave `clarification_answers` at
        its pre-clarify default (ADR-0003 §9, Q21: a prior version of this
        test resumed with `{}` and only checked the answers dict, which
        passed even when the interrupt silently never cleared at all — see
        `test_literal_empty_dict_resume_does_not_clear_the_clarify_interrupt`
        below for that failure mode, now pinned separately)."""
        _start(graph, _VAGUE_TASK, "s7")
        resumed = _resume(graph, "s7", "")
        assert "__interrupt__" not in resumed
        assert resumed["clarification_answers"] == {}
        assert resumed["clarification_attempted"] is True
        assert resumed["status"] == "done"

    def test_literal_empty_dict_resume_does_not_clear_the_clarify_interrupt(self, graph) -> None:
        """Pins a real LangGraph characteristic, confirmed empirically
        (ADR-0003 §9, Q21): `Command(resume={})` — a literal empty dict —
        is not delivered to `clarify` at all; the graph silently re-pauses
        at the same interrupt instead of resuming, and `_node_clarify`'s
        body never runs (no new `clarify` entry in `steps`). This is why
        every caller (the CLI, `resume_workflow()`'s own docstring) must use
        a non-dict falsy value like `""`, never `{}}`, to decline every
        question — see the previous test for the value that actually
        works."""
        started = _start(graph, _VAGUE_TASK, "s7b")
        steps_before = [s["node"] for s in started["steps"]]

        resumed = _resume(graph, "s7b", {})

        assert "__interrupt__" in resumed
        assert [s["node"] for s in resumed["steps"]] == steps_before

    def test_declining_every_question_does_not_repeat_the_interrupt(self, graph) -> None:
        """The actual Q21 regression: previously, declining every question
        made the graph re-raise `clarify` indefinitely. Now it must
        interrupt exactly once, reach a normal completion, and leave the
        unanswered fields genuinely unknown — never silently promoted to
        "known" or "assumed" just because the human was asked and didn't
        answer."""
        started = _start(graph, _VAGUE_TASK, "s7c")
        unknown_before = {
            f["name"] for f in started["requirements_analysis"]["fields"] if f["status"] == "unknown"
        }
        assert unknown_before  # sanity: the vague task really has unknowns

        resumed = _resume(graph, "s7c", "")

        assert "__interrupt__" not in resumed
        assert [s["node"] for s in resumed["steps"]].count("clarify") == 1
        assert resumed["status"] == "done"
        unknown_after = {
            f["name"] for f in resumed["requirements_analysis"]["fields"] if f["status"] == "unknown"
        }
        # Same task, same (still-empty) assumptions in both analyze_
        # requirements calls -> identical unknowns. Declining is never
        # silently read as an answer.
        assert unknown_after == unknown_before


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
        input_field_groups: tuple[RequiredFieldGroup, ...] = (),
        binding_id: str | None = None,
        description: str = "",
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
                binding_id=binding_id or f"{skill_id}-v1",
                runtime_id=rt.runtime_id,
                approval_policy=approval_policy,  # type: ignore[arg-type]
                verified=True,
                description=description,
                input_schema=input_schema,
                input_field_groups=input_field_groups,
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
            "candidate_descriptions": (),
            "missing_inputs": (),
            "conflicting_inputs": (),
            "selected_skill_id": "trt-perf-analysis",
            "selected_binding_id": "trt-perf-analysis-v1",
            "selected_input_schema": (),
            "selected_input_field_groups": (),
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
        """Since ADR-0010 §13, a first-pass missing_required_inputs result
        no longer terminates the run directly — it pauses at the new
        provide_execution_inputs interrupt instead. This still proves "no
        plan, no execution" up to the point of the pause; the recovery
        round itself (resuming this interrupt) is covered by
        TestProvideExecutionInputsRecovery below."""
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

        assert "__interrupt__" in result
        payload = result["__interrupt__"][0].value
        assert payload["type"] == "provide_execution_inputs"
        assert payload["skill_id"] == "trt-perf-analysis"
        assert payload["binding_id"] == "trt-perf-analysis-v1"
        assert payload["missing_inputs"] == [{"name": "path", "description": "folder path"}]

    def test_conflicting_pre_supplied_inputs_reject_before_approval_or_execution(
        self, tmp_path: Path
    ) -> None:
        """ADR-0010 §15 (review correction on PR #40): true oneOf/XOR — two
        group members pre-supplied together via execution_inputs (ADR-0010
        §12) at start_workflow() time, before any interrupt is even
        possible, must be rejected as "conflicting_inputs" and reach
        status == "done" without ever calling approval_gate's real gating
        logic or the runtime — no interrupt fires at all (unlike
        "missing_required_inputs", "conflicting_inputs" never routes to
        provide_execution_inputs; there is nothing to ask for, only
        something to remove)."""
        execution_registry = ExecutionBindingRegistry()
        runtime = self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=(
                InputField(name="path", required=False, description="folder path"),
                InputField(name="data", required=False, description="data list"),
            ),
            input_field_groups=(
                RequiredFieldGroup(kind="exactly_one", field_names=("path", "data")),
            ),
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        result = _start(
            graph,
            _PLANNING_TASK,
            "plan-conflict-1",
            execution_inputs={"path": "/data/clips", "data": [["layers.json"]]},
        )

        assert "__interrupt__" not in result
        assert result["pending_execution"] is None
        assert result["execution_result"] is None
        assert result["approval_decision"] == "not_required"
        assert result["status"] == "done"
        assert result["planning_result"]["status"] == "conflicting_inputs"
        assert result["planning_result"]["plan"] is None
        assert sorted(result["planning_result"]["conflicting_inputs"]) == ["data", "path"]
        assert sorted(result["planning_result"]["missing_inputs"]) == []
        plan_step = next(s for s in result["steps"] if s["node"] == "plan_execution")
        assert plan_step["planning_status"] == "conflicting_inputs"
        assert sorted(plan_step["conflicting_inputs"]) == ["data", "path"]
        assert runtime.calls == []

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


class TestProvideExecutionInputsRecovery:
    """
    ADR-0010 §13: same-session recovery from planning_result.status ==
    "missing_required_inputs" via the new provide_execution_inputs
    interrupt. Self-contained fixtures, same convention as
    TestPlanExecutionIntegration (not reused directly, to keep each class's
    tests independently readable/runnable).
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
        input_field_groups: tuple[RequiredFieldGroup, ...] = (),
        binding_id: str | None = None,
    ) -> "FakeRuntime":
        rt = FakeRuntime(
            runtime_id=f"fake-runtime-{skill_id}",
            outcome=RuntimeOutcome(success=True, output={"ok": True}),
        )
        execution_registry.register_runtime(rt)
        execution_registry.register_binding(
            ExecutionBinding(
                skill_id=skill_id,
                binding_id=binding_id or f"{skill_id}-v1",
                runtime_id=rt.runtime_id,
                approval_policy=approval_policy,  # type: ignore[arg-type]
                verified=True,
                input_schema=input_schema,
                input_field_groups=input_field_groups,
            )
        )
        return rt

    _XOR_SCHEMA = (
        InputField(name="path", required=False, description="folder path"),
        InputField(name="data", required=False, description="data list"),
    )
    _XOR_GROUP = (RequiredFieldGroup(kind="exactly_one", field_names=("path", "data")),)

    _TWO_REQUIRED_SCHEMA = (
        InputField(name="path", required=True, description="folder path"),
        InputField(name="model_name", required=True, description="model label"),
    )

    # ── Full, valid resume ("supplied") ─────────────────────────────────

    def test_full_valid_resume_produces_a_plan_and_reaches_approval_gate(
        self, tmp_path: Path
    ) -> None:
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=(InputField(name="path", required=True, description="folder path"),),
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        started = _start(graph, _PLANNING_TASK, "rec-1")
        assert started["__interrupt__"][0].value["type"] == "provide_execution_inputs"

        resumed = _resume(graph, "rec-1", {"path": "/data/clips"})

        assert "__interrupt__" not in resumed
        assert resumed["status"] == "done"
        assert resumed["pending_execution"] == {
            "skill_id": "trt-perf-analysis",
            "inputs": {"path": "/data/clips"},
            "task": _PLANNING_TASK,
        }
        assert resumed["execution_result"]["status"] == "completed"
        recovery = resumed["execution_input_recovery"]
        assert recovery["outcome"] == "supplied"
        assert recovery["terminal"] is False
        assert recovery["accepted"] == ["path"]
        assert recovery["still_missing"] == []

    def test_full_input_field_contract_survives_the_real_checkpoint_round_trip(
        self, tmp_path: Path
    ) -> None:
        """
        Explicit verification (requested on PR #33 review): the
        identity+schema guard's `expected_input_schema` snapshot must
        preserve the FULL InputField contract — name, required, description,
        AND default — not just field names, through the real checkpoint
        (MemorySaver, via _start()/_resume(), not a bypassed/mocked path),
        and the comparison must be deterministic (no false-positive
        "schema_changed" for a genuinely unchanged binding). A multi-field
        schema with a non-None default and real description text is used
        deliberately, since a single bare-minimum field wouldn't exercise
        default/description at all.
        """
        schema = (
            InputField(name="path", required=True, description="folder containing layer JSON"),
            InputField(
                name="model_name",
                required=True,
                description="human-readable model label",
                default="unnamed-model",
            ),
        )
        execution_registry = ExecutionBindingRegistry()
        self._register(execution_registry, "trt-perf-analysis", input_schema=schema)
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        started = _start(graph, _PLANNING_TASK, "rec-verify-1")
        payload = started["__interrupt__"][0].value
        # The payload itself (built pre-interrupt from the checkpointed
        # planning_result, never a live lookup — ADR-0010 §13.3) already
        # carries per-field descriptions, proving more than bare names
        # reached this point.
        assert {"name": "path", "description": "folder containing layer JSON"} in payload[
            "missing_inputs"
        ]
        assert {
            "name": "model_name",
            "description": "human-readable model label",
        } in payload["missing_inputs"]

        resumed = _resume(
            graph, "rec-verify-1", {"path": "/data/clips", "model_name": "resnet50"}
        )

        recovery = resumed["execution_input_recovery"]
        # No false-positive mismatch for a binding that never actually
        # changed — proves the structural comparison is correct, not just
        # permissive.
        assert recovery["outcome"] == "supplied"
        assert recovery["terminal"] is False
        assert recovery["mismatch_detail"] is None
        # The stored snapshot itself carries all four InputField fields per
        # entry, in declaration order — not just names.
        assert recovery["expected_input_schema"] == [
            {
                "name": "path",
                "required": True,
                "description": "folder containing layer JSON",
                "default": None,
            },
            {
                "name": "model_name",
                "required": True,
                "description": "human-readable model label",
                "default": "unnamed-model",
            },
        ]
        assert resumed["pending_execution"] == {
            "skill_id": "trt-perf-analysis",
            "inputs": {"path": "/data/clips", "model_name": "resnet50"},
            "task": _PLANNING_TASK,
        }

    def test_approval_required_binding_still_gates_after_successful_recovery(
        self, tmp_path: Path
    ) -> None:
        execution_registry = ExecutionBindingRegistry()
        runtime = self._register(
            execution_registry,
            "trt-perf-analysis",
            approval_policy="approval_required",
            input_schema=(InputField(name="path", required=True, description="folder path"),),
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        _start(graph, _PLANNING_TASK, "rec-2")
        after_recovery = _resume(graph, "rec-2", {"path": "/data/clips"})

        # A valid recovery must not itself execute or auto-approve — a
        # second, independent interrupt (approval) is still required.
        assert "__interrupt__" in after_recovery
        assert after_recovery["__interrupt__"][0].value["type"] == "approval"
        assert runtime.calls == []

        approved = _resume(graph, "rec-2", "approved")
        assert approved["approval_decision"] == "approved"
        assert approved["execution_result"]["status"] == "completed"
        assert runtime.calls == [("trt-perf-analysis", {"path": "/data/clips"})]

    # ── Mutually-exclusive field groups (ADR-0009 §12 / ADR-0010 §14, Q20) ──

    def test_group_interrupt_names_every_member_and_the_group_itself(
        self, tmp_path: Path
    ) -> None:
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=self._XOR_SCHEMA,
            input_field_groups=self._XOR_GROUP,
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        started = _start(graph, _PLANNING_TASK, "rec-group-1")
        payload = started["__interrupt__"][0].value

        assert {m["name"] for m in payload["missing_inputs"]} == {"path", "data"}
        assert payload["field_groups"] == [
            {"kind": "exactly_one", "field_names": ["path", "data"]}
        ]

    def test_supplying_only_one_group_member_recovers_as_supplied(
        self, tmp_path: Path
    ) -> None:
        """Requiring BOTH path and data to answer the interrupt would
        misrepresent the real "exactly one" contract — this is the core
        behavior Q20 closes."""
        execution_registry = ExecutionBindingRegistry()
        runtime = self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=self._XOR_SCHEMA,
            input_field_groups=self._XOR_GROUP,
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        _start(graph, _PLANNING_TASK, "rec-group-2")
        resumed = _resume(graph, "rec-group-2", {"data": [["layers.json"]]})

        assert "__interrupt__" not in resumed
        recovery = resumed["execution_input_recovery"]
        assert recovery["outcome"] == "supplied"
        assert recovery["terminal"] is False
        assert recovery["accepted"] == ["data"]
        assert recovery["still_missing"] == []
        assert resumed["pending_execution"] == {
            "skill_id": "trt-perf-analysis",
            "inputs": {"data": [["layers.json"]]},
            "task": _PLANNING_TASK,
        }
        assert resumed["execution_result"]["status"] == "completed"
        assert runtime.calls == [("trt-perf-analysis", {"data": [["layers.json"]]})]

    def test_supplying_neither_group_member_is_invalid(self, tmp_path: Path) -> None:
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=self._XOR_SCHEMA,
            input_field_groups=self._XOR_GROUP,
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        _start(graph, _PLANNING_TASK, "rec-group-3")
        resumed = _resume(graph, "rec-group-3", {"model_name": "resnet50"})

        recovery = resumed["execution_input_recovery"]
        assert recovery["outcome"] == "invalid"
        assert recovery["terminal"] is True
        assert resumed["pending_execution"] is None

    def test_supplying_both_group_members_at_the_interrupt_is_conflicting(
        self, tmp_path: Path
    ) -> None:
        """ADR-0010 §15 (review correction on PR #40): true oneOf/XOR — a
        human who answers a provide_execution_inputs interrupt with BOTH
        path and data must not recover as "supplied"; the run terminates
        with an actionable "conflicting" outcome, never reaching
        approval_gate or execute."""
        execution_registry = ExecutionBindingRegistry()
        runtime = self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=self._XOR_SCHEMA,
            input_field_groups=self._XOR_GROUP,
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        _start(graph, _PLANNING_TASK, "rec-group-6")
        resumed = _resume(
            graph, "rec-group-6", {"path": "/data/clips", "data": [["layers.json"]]}
        )

        assert "__interrupt__" not in resumed
        recovery = resumed["execution_input_recovery"]
        assert recovery["outcome"] == "conflicting"
        assert recovery["terminal"] is True
        assert recovery["conflicting"] == ["data", "path"]
        assert resumed["pending_execution"] is None
        assert resumed["approval_decision"] is None
        assert resumed["execution_result"] is None
        assert resumed["status"] == "done"
        assert runtime.calls == []

    def test_conflict_introduced_by_an_unsolicited_extra_field_is_still_caught(
        self, tmp_path: Path
    ) -> None:
        """A subtler path to the same violation: `path` is already known
        (pre-supplied via execution_inputs, satisfying the group before the
        interrupt ever fires) and a genuinely missing, unrelated field
        (model_name) triggers the interrupt. The human answers the actual
        ask (model_name) but ALSO includes "data" — a declared name the
        interrupt never requested, since the group looked satisfied at plan
        time. _classify_execution_input_resume's own per-round check has no
        visibility into a group outside `requested`, so it reports
        "supplied" — only the retry's fresh, authoritative plan_execution()
        call (run against the fully merged execution_inputs) can catch that
        this now conflicts. Proves the ADR-0010 §15 conflicting_inputs
        branch in _node_plan_execution's retry, not just the classify-layer
        shortcut."""
        schema = self._XOR_SCHEMA + (
            InputField(name="model_name", required=True, description="model label"),
        )
        execution_registry = ExecutionBindingRegistry()
        runtime = self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=schema,
            input_field_groups=self._XOR_GROUP,
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        started = _start(
            graph, _PLANNING_TASK, "rec-group-7", execution_inputs={"path": "/data/clips"}
        )
        assert started["__interrupt__"][0].value["missing_inputs"] == [
            {"name": "model_name", "description": "model label"}
        ]

        resumed = _resume(
            graph, "rec-group-7", {"model_name": "resnet50", "data": [["layers.json"]]}
        )

        assert "__interrupt__" not in resumed
        recovery = resumed["execution_input_recovery"]
        assert recovery["outcome"] == "conflicting"
        assert recovery["terminal"] is True
        assert recovery["mismatch_detail"] == "conflicting_inputs_supplied"
        assert resumed["pending_execution"] is None
        assert resumed["execution_result"] is None
        assert resumed["planning_result"]["status"] == "conflicting_inputs"
        assert sorted(resumed["planning_result"]["conflicting_inputs"]) == ["data", "path"]
        assert runtime.calls == []

    def test_group_and_individually_required_field_together_incomplete_when_only_group_met(
        self, tmp_path: Path
    ) -> None:
        schema = self._XOR_SCHEMA + (
            InputField(name="model_name", required=True, description="model label"),
        )
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=schema,
            input_field_groups=self._XOR_GROUP,
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        _start(graph, _PLANNING_TASK, "rec-group-4")
        resumed = _resume(graph, "rec-group-4", {"path": "/data/clips"})  # model_name omitted

        recovery = resumed["execution_input_recovery"]
        assert recovery["outcome"] == "incomplete"
        assert recovery["terminal"] is True
        assert recovery["accepted"] == ["path"]
        assert recovery["still_missing"] == ["model_name"]
        assert resumed["pending_execution"] is None

    def test_group_changed_underneath_the_pause_is_detected_as_schema_changed(
        self, tmp_path: Path
    ) -> None:
        """Same binding_id, same individual input_schema, but the group
        constraint itself changed while paused — must still be caught, not
        just an input_schema-only comparison (ADR-0010 §14)."""
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=self._XOR_SCHEMA,
            input_field_groups=self._XOR_GROUP,
            binding_id="stable-id-v2",
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        _start(graph, _PLANNING_TASK, "rec-group-5")

        # Re-register the same binding_id and the same input_schema, but
        # drop the group entirely (path/data become "presence not required
        # at all" instead of "exactly one required") — a real, structural
        # contract change with no visible input_schema difference.
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=self._XOR_SCHEMA,
            input_field_groups=(),
            binding_id="stable-id-v2",
        )

        resumed = _resume(graph, "rec-group-5", {"data": [["layers.json"]]})

        recovery = resumed["execution_input_recovery"]
        assert recovery["outcome"] == "binding_mismatch"
        assert recovery["mismatch_detail"] == "schema_changed"
        assert recovery["terminal"] is True
        assert resumed["pending_execution"] is None

    # ── Incomplete / invalid / cancelled — all terminal, no second ask ────

    def test_partial_resume_is_incomplete_and_terminates_without_approval(
        self, tmp_path: Path
    ) -> None:
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry, "trt-perf-analysis", input_schema=self._TWO_REQUIRED_SCHEMA
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        _start(graph, _PLANNING_TASK, "rec-3")
        resumed = _resume(graph, "rec-3", {"path": "/data/clips"})  # model_name omitted

        assert "__interrupt__" not in resumed
        assert resumed["status"] == "done"
        assert resumed["pending_execution"] is None
        assert resumed["approval_decision"] is None
        assert resumed["execution_result"] is None
        recovery = resumed["execution_input_recovery"]
        assert recovery["outcome"] == "incomplete"
        assert recovery["terminal"] is True
        assert recovery["accepted"] == ["path"]
        assert recovery["still_missing"] == ["model_name"]
        assert resumed["planning_result"]["status"] == "missing_required_inputs"

    def test_mixed_valid_and_invalid_values_still_classify_as_incomplete(
        self, tmp_path: Path
    ) -> None:
        """One field valid, the other explicitly attempted but blank — not
        merely omitted. Must classify identically to a plain omission:
        "incomplete", not a distinct category, per ADR-0010 §13's
        deterministic classification rule."""
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry, "trt-perf-analysis", input_schema=self._TWO_REQUIRED_SCHEMA
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        _start(graph, _PLANNING_TASK, "rec-4")
        resumed = _resume(graph, "rec-4", {"path": "/data/clips", "model_name": "   "})

        recovery = resumed["execution_input_recovery"]
        assert recovery["outcome"] == "incomplete"
        assert recovery["terminal"] is True
        assert recovery["accepted"] == ["path"]
        assert recovery["still_missing"] == ["model_name"]
        assert recovery["rejected"] == [{"name": "model_name", "reason": "blank"}]
        assert resumed["pending_execution"] is None

    def test_all_invalid_values_result_in_invalid_outcome(self, tmp_path: Path) -> None:
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=(InputField(name="path", required=True, description="folder path"),),
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        _start(graph, _PLANNING_TASK, "rec-5")
        resumed = _resume(
            graph, "rec-5", {"path": "", "totally_unrelated_field": "x"}
        )

        recovery = resumed["execution_input_recovery"]
        assert recovery["outcome"] == "invalid"
        assert recovery["terminal"] is True
        assert recovery["accepted"] == []
        assert recovery["still_missing"] == ["path"]
        assert {"name": "path", "reason": "blank"} in recovery["rejected"]
        assert {"name": "totally_unrelated_field", "reason": "not_declared"} in recovery["rejected"]
        assert resumed["pending_execution"] is None
        assert resumed["approval_decision"] is None
        assert resumed["execution_result"] is None

    def test_empty_resume_is_cancelled(self, tmp_path: Path) -> None:
        """Resume with a falsy, non-mapping value — an empty string, not a
        literal `{}`. Confirmed empirically (not assumed): LangGraph's
        `Command(resume=...)` does not actually deliver a literal empty
        dict — the graph silently re-pauses at the same interrupt instead
        of resuming, the same latent gap `clarify`'s own resume handling
        has (its test suite's existing `Command(resume=None)` comment
        claims "`{}` is the correct way to represent no answer", which this
        node's own tests found does not hold for an empty *dict*
        specifically — `None` and `{}` both fail to deliver; any other
        falsy value, e.g. `""`, delivers correctly). This node's own
        classification logic (`_classify_execution_input_resume`) already
        handles a literal `{}` correctly *if* it were ever delivered — the
        constraint is LangGraph's, not this node's — so this test exercises
        the same "declined" code path through a value LangGraph actually
        delivers, rather than asserting on an undeliverable one."""
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=(InputField(name="path", required=True, description="folder path"),),
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        _start(graph, _PLANNING_TASK, "rec-6")
        resumed = _resume(graph, "rec-6", "")

        assert "__interrupt__" not in resumed
        recovery = resumed["execution_input_recovery"]
        assert recovery["outcome"] == "cancelled"
        assert recovery["terminal"] is True
        assert resumed["pending_execution"] is None
        assert resumed["approval_decision"] is None
        assert resumed["execution_result"] is None

    def test_non_mapping_resume_is_treated_as_cancelled_no_crash(
        self, tmp_path: Path
    ) -> None:
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=(InputField(name="path", required=True, description="folder path"),),
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        _start(graph, _PLANNING_TASK, "rec-7")
        resumed = _resume(graph, "rec-7", "oops not a dict")

        recovery = resumed["execution_input_recovery"]
        assert recovery["outcome"] == "cancelled"
        assert recovery["terminal"] is True
        assert resumed["pending_execution"] is None

    def test_recovery_is_one_shot_no_second_interrupt(self, tmp_path: Path) -> None:
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry, "trt-perf-analysis", input_schema=self._TWO_REQUIRED_SCHEMA
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        _start(graph, _PLANNING_TASK, "rec-8")
        # Deliberately still incomplete after this one resume.
        resumed = _resume(graph, "rec-8", {"path": "/data/clips"})

        assert "__interrupt__" not in resumed
        assert resumed["status"] == "done"
        assert [s["node"] for s in resumed["steps"]].count("provide_execution_inputs") == 1

    def test_clarification_answers_and_execution_inputs_stay_separate(
        self, tmp_path: Path
    ) -> None:
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=(InputField(name="path", required=True, description="folder path"),),
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        _start(graph, _PLANNING_TASK, "rec-9")
        resumed = _resume(graph, "rec-9", {"path": "/data/clips"})

        assert resumed["clarification_answers"] == {}
        assert resumed["execution_inputs"] == {"path": "/data/clips"}

    # ── Binding identity / schema mutated during the pause ────────────────

    def test_binding_identity_changed_during_pause_is_detected(
        self, tmp_path: Path
    ) -> None:
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=(InputField(name="path", required=True, description="folder path"),),
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        _start(graph, _PLANNING_TASK, "rec-10")

        # Re-register a DIFFERENT binding_id under the same skill_id while
        # the run sits paused — simulates a registry mutation mid-wait.
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=(InputField(name="path", required=True, description="folder path"),),
            binding_id="trt-perf-analysis-v2-different",
        )

        resumed = _resume(graph, "rec-10", {"path": "/data/clips"})

        assert "__interrupt__" not in resumed
        recovery = resumed["execution_input_recovery"]
        assert recovery["outcome"] == "binding_mismatch"
        assert recovery["mismatch_detail"] == "identity_changed"
        assert recovery["terminal"] is True
        assert resumed["pending_execution"] is None
        assert resumed["approval_decision"] is None
        assert resumed["execution_result"] is None
        # Even though the fresh plan_execution() call itself would have
        # reported "planned" for the new binding — the mismatch guard
        # overrides it, never silently switching to a different binding.
        assert resumed["planning_result"]["status"] == "planned"

    def test_schema_changed_same_binding_id_is_detected(self, tmp_path: Path) -> None:
        """ID equality alone must not be trusted: the same binding_id is
        re-registered with a structurally different input_schema (an extra
        required field) while the run is paused."""
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=(InputField(name="path", required=True, description="folder path"),),
            binding_id="stable-id-v1",
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        _start(graph, _PLANNING_TASK, "rec-11")

        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=self._TWO_REQUIRED_SCHEMA,  # path + model_name now
            binding_id="stable-id-v1",  # same binding_id as before
        )

        resumed = _resume(graph, "rec-11", {"path": "/data/clips"})

        recovery = resumed["execution_input_recovery"]
        assert recovery["outcome"] == "binding_mismatch"
        assert recovery["mismatch_detail"] == "schema_changed"
        assert recovery["terminal"] is True
        assert resumed["pending_execution"] is None
        assert resumed["approval_decision"] is None
        assert resumed["execution_result"] is None

    # ── Precedence / first-pass regressions ───────────────────────────────

    def test_caller_supplied_pending_execution_never_triggers_this_interrupt(
        self, tmp_path: Path
    ) -> None:
        execution_registry = ExecutionBindingRegistry()
        self._register(
            execution_registry,
            "trt-perf-analysis",
            input_schema=(InputField(name="path", required=True, description="folder path"),),
        )
        graph = self._graph_for(tmp_path, execution_registry, skill_ids=("trt-perf-analysis",))

        result = _start(
            graph,
            _PLANNING_TASK,
            "rec-12",
            pending_execution={"skill_id": "trt-perf-analysis", "inputs": {}, "task": "t"},
        )

        assert "__interrupt__" not in result
        assert result["execution_input_recovery"] is None
        assert result["planning_result"] is None
        assert result["pending_execution"]["skill_id"] == "trt-perf-analysis"


class TestChooseCandidateInterrupt:
    """
    ADR-0010 §16 (Q18): the fourth interrupt kind. Ambiguous executable
    candidates pause at `choose_candidate` instead of silently producing no
    plan; the human's bare-skill_id answer is validated against the exact
    offered set, persisted, and fed back into a fresh plan_execution().
    Every test drives the real compiled graph + real MemorySaver checkpoint
    (via _start/_resume), never a bypassed node.
    """

    _register = staticmethod(TestPlanExecutionIntegration._register)

    def _graph_for(
        self,
        tmp_path: Path,
        execution_registry: ExecutionBindingRegistry,
        *,
        skill_ids: tuple[str, ...],
    ) -> Any:
        return TestPlanExecutionIntegration()._graph_for(
            tmp_path, execution_registry, skill_ids=skill_ids
        )

    _IDS = ("bench-tool-b", "trt-perf-analysis")

    def _two(self, tmp_path: Path, **kwargs: Any):
        registry = ExecutionBindingRegistry()
        rt_a = self._register(
            registry, "trt-perf-analysis", description="TensorRT layer analysis", **kwargs
        )
        rt_b = self._register(registry, "bench-tool-b", description="Generic benchmark tool")
        graph = self._graph_for(tmp_path, registry, skill_ids=self._IDS)
        return graph, registry, rt_a, rt_b

    # ── The pause itself ─────────────────────────────────────────────────

    def test_ambiguity_pauses_with_every_candidate_id_and_description(
        self, tmp_path: Path
    ) -> None:
        graph, _, rt_a, rt_b = self._two(tmp_path)

        started = _start(graph, _PLANNING_TASK, "cand-1")

        assert "__interrupt__" in started
        payload = started["__interrupt__"][0].value
        assert payload["type"] == "choose_candidate"
        assert payload["candidates"] == [
            {"skill_id": "bench-tool-b", "description": "Generic benchmark tool"},
            {"skill_id": "trt-perf-analysis", "description": "TensorRT layer analysis"},
        ]
        assert started["pending_execution"] is None
        assert started["execution_result"] is None
        assert rt_a.calls == [] and rt_b.calls == []

    # ── Valid choice ─────────────────────────────────────────────────────

    def test_valid_choice_is_persisted_and_planning_resumes_with_only_that_skill(
        self, tmp_path: Path
    ) -> None:
        graph, _, rt_a, rt_b = self._two(tmp_path)

        _start(graph, _PLANNING_TASK, "cand-2")
        resumed = _resume(graph, "cand-2", "bench-tool-b")

        assert "__interrupt__" not in resumed
        assert resumed["candidate_choice"] == "bench-tool-b"
        selection = resumed["candidate_selection"]
        assert selection["outcome"] == "selected"
        assert selection["terminal"] is False
        assert selection["chosen_skill_id"] == "bench-tool-b"
        assert sorted(selection["expected_candidate_skill_ids"]) == list(self._IDS)
        assert resumed["planning_result"]["status"] == "planned"
        assert resumed["pending_execution"]["skill_id"] == "bench-tool-b"
        assert resumed["execution_result"]["status"] == "completed"
        assert resumed["status"] == "done"
        assert [c[0] for c in rt_b.calls] == ["bench-tool-b"]
        assert rt_a.calls == []  # the other candidate is never touched

    def test_choice_of_the_other_candidate_runs_the_other_skill(self, tmp_path: Path) -> None:
        graph, _, rt_a, rt_b = self._two(tmp_path)

        _start(graph, _PLANNING_TASK, "cand-3")
        resumed = _resume(graph, "cand-3", "trt-perf-analysis")

        assert resumed["pending_execution"]["skill_id"] == "trt-perf-analysis"
        assert [c[0] for c in rt_a.calls] == ["trt-perf-analysis"]
        assert rt_b.calls == []

    def test_surrounding_whitespace_in_the_choice_is_tolerated(self, tmp_path: Path) -> None:
        graph, _, _, rt_b = self._two(tmp_path)

        _start(graph, _PLANNING_TASK, "cand-4")
        resumed = _resume(graph, "cand-4", "  bench-tool-b \n")

        assert resumed["candidate_selection"]["outcome"] == "selected"
        assert [c[0] for c in rt_b.calls] == ["bench-tool-b"]

    # ── Never silently choose: every non-selection is terminal ───────────

    @pytest.mark.parametrize(
        "answer, outcome",
        [
            ("definitely-not-offered", "invalid"),
            ("bench-tool", "invalid"),  # a prefix/"closest match" is not a match
            ("BENCH-TOOL-B", "invalid"),  # exact match only, no case folding
            ("", "cancelled"),
            ("   ", "cancelled"),
            ({"skill_id": "bench-tool-b"}, "cancelled"),  # wrong shape, never coerced
            (0, "cancelled"),
        ],
    )
    def test_invalid_or_cancelled_choice_is_terminal_and_executes_nothing(
        self, tmp_path: Path, answer: Any, outcome: str
    ) -> None:
        graph, _, rt_a, rt_b = self._two(tmp_path)

        _start(graph, _PLANNING_TASK, "cand-5")
        resumed = _resume(graph, "cand-5", answer)

        assert "__interrupt__" not in resumed  # one shot, never a second prompt
        selection = resumed["candidate_selection"]
        assert selection["outcome"] == outcome
        assert selection["terminal"] is True
        assert selection["chosen_skill_id"] is None
        assert resumed.get("candidate_choice") is None
        assert resumed["pending_execution"] is None
        assert resumed["approval_decision"] is None  # approval_gate bypassed
        assert resumed["execution_result"] is None
        assert resumed["status"] == "done"
        assert rt_a.calls == [] and rt_b.calls == []

    def test_chosen_skill_deregistered_during_the_pause_never_falls_back_to_the_other(
        self, tmp_path: Path
    ) -> None:
        """With bench-tool-b's binding removed mid-pause only trt-perf-
        analysis remains, so a naive retry would see ONE candidate and plan
        it — silently running a skill the human did not pick. Must be a
        terminal candidate_mismatch instead."""
        graph, registry, rt_a, rt_b = self._two(tmp_path)

        _start(graph, _PLANNING_TASK, "cand-6")
        del registry._bindings["bench-tool-b"]  # simulate a mid-pause registry change
        resumed = _resume(graph, "cand-6", "bench-tool-b")

        selection = resumed["candidate_selection"]
        assert selection["outcome"] == "candidate_mismatch"
        assert selection["terminal"] is True
        assert resumed["pending_execution"] is None
        assert resumed["execution_result"] is None
        assert resumed["status"] == "done"
        assert rt_a.calls == [] and rt_b.calls == []

    # ── Composition with the other interrupt kinds ───────────────────────

    def test_chosen_candidate_then_missing_inputs_chains_into_the_input_recovery(
        self, tmp_path: Path
    ) -> None:
        """choose_candidate resolves ambiguity, the now-unambiguous
        candidate is missing a required input, so the SECOND, separate
        provide_execution_inputs interrupt follows — each bounded to one
        round, each finalized exactly once."""
        registry = ExecutionBindingRegistry()
        self._register(registry, "trt-perf-analysis")
        rt_b = self._register(
            registry,
            "bench-tool-b",
            input_schema=(InputField(name="path", required=True, description="folder"),),
        )
        graph = self._graph_for(tmp_path, registry, skill_ids=self._IDS)

        first = _start(graph, _PLANNING_TASK, "cand-7")
        assert first["__interrupt__"][0].value["type"] == "choose_candidate"

        second = _resume(graph, "cand-7", "bench-tool-b")
        assert second["__interrupt__"][0].value["type"] == "provide_execution_inputs"
        assert second["__interrupt__"][0].value["skill_id"] == "bench-tool-b"
        assert second["candidate_selection"]["terminal"] is False

        done = _resume(graph, "cand-7", {"path": "/data/clips"})
        assert "__interrupt__" not in done
        assert done["candidate_selection"]["outcome"] == "selected"
        assert done["candidate_selection"]["terminal"] is False  # not re-finalized
        assert done["execution_input_recovery"]["outcome"] == "supplied"
        assert done["pending_execution"] == {
            "skill_id": "bench-tool-b",
            "inputs": {"path": "/data/clips"},
            "task": _PLANNING_TASK,
        }
        assert rt_b.calls == [("bench-tool-b", {"path": "/data/clips"})]

    def test_approval_required_choice_still_reaches_the_approval_gate(
        self, tmp_path: Path
    ) -> None:
        registry = ExecutionBindingRegistry()
        self._register(registry, "trt-perf-analysis")
        rt_b = self._register(registry, "bench-tool-b", approval_policy="approval_required")
        graph = self._graph_for(tmp_path, registry, skill_ids=self._IDS)

        _start(graph, _PLANNING_TASK, "cand-8")
        gated = _resume(graph, "cand-8", "bench-tool-b")

        assert gated["__interrupt__"][0].value["type"] == "approval"
        assert rt_b.calls == []  # choosing is not approving
        approved = _resume(graph, "cand-8", "approved")
        assert approved["execution_result"]["status"] == "completed"
        assert [c[0] for c in rt_b.calls] == ["bench-tool-b"]

    # ── Existing behavior preserved ──────────────────────────────────────

    def test_caller_supplied_pending_execution_bypasses_disambiguation(
        self, tmp_path: Path
    ) -> None:
        """Direct execution intent (ADR-0010 §10) is never second-guessed:
        even with two ambiguous candidates in play, a caller-supplied
        pending_execution runs as given, with no choose_candidate interrupt
        and no planning_result."""
        graph, _, rt_a, rt_b = self._two(tmp_path)

        result = _start(
            graph,
            _PLANNING_TASK,
            "cand-9",
            pending_execution={"skill_id": "bench-tool-b", "inputs": {}, "task": "t"},
        )

        assert "__interrupt__" not in result
        assert result["planning_result"] is None
        assert result.get("candidate_selection") is None
        assert result["execution_result"]["status"] == "completed"
        assert [c[0] for c in rt_b.calls] == ["bench-tool-b"]
        assert rt_a.calls == []

    def test_a_single_candidate_never_raises_the_interrupt(self, tmp_path: Path) -> None:
        registry = ExecutionBindingRegistry()
        rt = self._register(registry, "trt-perf-analysis")
        graph = self._graph_for(tmp_path, registry, skill_ids=("trt-perf-analysis",))

        result = _start(graph, _PLANNING_TASK, "cand-10")

        assert "__interrupt__" not in result
        assert result.get("candidate_selection") is None
        assert [c[0] for c in rt.calls] == ["trt-perf-analysis"]


class TestChooseCandidateThroughCVAgent:
    """ADR-0010 §16 (Q18) through the real `CVAgent.start_workflow()`/
    `.resume_workflow()` API — real skill discovery, real `AgentConfig`,
    real durable Project Memory (pinned to tmp_path, ADR-0004 §1 item 13) —
    not only the raw compiled graph."""

    def _agent(self, tmp_path: Path):
        from cv_agent.config.settings import AgentConfig
        from cv_agent.runtime.agent import CVAgent

        skills = tmp_path / "skills"
        for skill_id in ("bench-tool-b", "trt-perf-analysis"):
            _write_planning_skill(skills, skill_id)
        agent = CVAgent(AgentConfig(skill_paths=(skills,), workspace_root=tmp_path))
        runtimes = {}
        for skill_id in ("bench-tool-b", "trt-perf-analysis"):
            rt = FakeRuntime(
                runtime_id=f"fake-runtime-{skill_id}",
                outcome=RuntimeOutcome(success=True, output={"ok": True}),
            )
            runtimes[skill_id] = rt
            agent.execution_bindings.register_runtime(rt)
            agent.execution_bindings.register_binding(
                ExecutionBinding(
                    skill_id=skill_id,
                    binding_id=f"{skill_id}-v1",
                    runtime_id=rt.runtime_id,
                    approval_policy="allowed",
                    verified=True,
                    description=f"desc of {skill_id}",
                )
            )
        return agent, runtimes

    def test_start_pauses_and_resume_with_a_valid_choice_executes_only_that_skill(
        self, tmp_path: Path
    ) -> None:
        agent, runtimes = self._agent(tmp_path)

        paused = agent.start_workflow(_PLANNING_TASK, session_id="cva-cand-1")

        payload = paused["__interrupt__"][0].value
        assert payload["type"] == "choose_candidate"
        assert payload["candidates"] == [
            {"skill_id": "bench-tool-b", "description": "desc of bench-tool-b"},
            {"skill_id": "trt-perf-analysis", "description": "desc of trt-perf-analysis"},
        ]
        assert paused["candidate_selection"] is None  # nothing decided yet

        resumed = agent.resume_workflow("cva-cand-1", "trt-perf-analysis")

        assert resumed["status"] == "done"
        assert resumed["candidate_selection"]["outcome"] == "selected"
        assert [c[0] for c in runtimes["trt-perf-analysis"].calls] == ["trt-perf-analysis"]
        assert runtimes["bench-tool-b"].calls == []
        assert agent.memory.get_session("cva-cand-1").status == "done"

    def test_resume_with_an_unoffered_skill_is_terminal_and_runs_nothing(
        self, tmp_path: Path
    ) -> None:
        agent, runtimes = self._agent(tmp_path)

        agent.start_workflow(_PLANNING_TASK, session_id="cva-cand-2")
        resumed = agent.resume_workflow("cva-cand-2", "some-other-skill")

        assert resumed["candidate_selection"]["outcome"] == "invalid"
        assert resumed["candidate_selection"]["terminal"] is True
        assert resumed["execution_result"] is None
        assert all(rt.calls == [] for rt in runtimes.values())
