"""
Tests for the real (non-synthetic) interrupt input-handling `python -m
cv_agent workflow` gained in this change (issue #34): `_resume_value_for_
interrupt`, `_run_workflow_interactive`, `_print_workflow_summary`, and
`WorkflowStuckError`, all in `cv_agent/__main__.py`.

Three layers, matching `tests/test_cli_execute.py`'s own convention of
testing pure CLI helper functions directly (no subprocess, no argparse)
alongside end-to-end CLI-as-subprocess tests (those live in
`tests/test_cli.py::TestCLISkillsCapabilitiesResolve`, extended by this
same change):

1. TestResumeValueForInterrupt — pure dispatch logic, one payload at a
   time, no graph involved.
2. TestRunWorkflowInteractiveStuckGuard — the CLI-only safety cap against
   a real, pre-existing, out-of-scope gap in `cv_agent/graph/workflow.py`'s
   own `_route_after_analysis` (see `_MAX_INTERRUPT_ROUNDS`'s docstring),
   using a fake agent so the cap itself is tested deterministically and
   fast, independent of actually reproducing that gap.
3. TestRunWorkflowInteractiveFixtureGraph — a real, unfaked
   `build_requirements_workflow_graph()` graph with a synthetic fixture
   binding (same honesty posture `tests/test_workflow.py`'s own
   `TestProvideExecutionInputsRecovery` already uses for Q20 — no real
   installed skill has a required input or an approval_required policy
   today), driving `_run_workflow_interactive` through
   provide_execution_inputs and approval_gate — interrupt kinds no CLI
   subprocess test can reach, since `_cmd_workflow` deliberately never
   registers a binding (see its own docstring).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from cv_agent.__main__ import (
    WorkflowStuckError,
    _MAX_INTERRUPT_ROUNDS,
    _print_workflow_summary,
    _resume_value_for_interrupt,
    _run_workflow_interactive,
)
from cv_agent.capabilities.registry import CapabilityRegistry
from cv_agent.execution.binding import ExecutionBinding, ExecutionBindingRegistry, InputField
from cv_agent.execution.executor import SkillExecutor
from cv_agent.execution.models import RuntimeOutcome
from cv_agent.graph.workflow import build_requirements_workflow_graph
from cv_agent.requirements.analyzer import RequirementsAnalyzer
from cv_agent.skills.inventory import SkillInventory
from cv_agent.skills.local import LocalSkillSource
from cv_agent.skills.resolver import TaskResolver

_REGISTRY_PATH = Path(__file__).parent.parent / "spec" / "capability_registry.json"


class TestResumeValueForInterrupt:
    """Pure dispatch logic — no graph, no subprocess."""

    def _clarification_payload(self) -> dict[str, Any]:
        return {
            "type": "clarification",
            "questions": [
                {
                    "relates_to_field": "deployment_target",
                    "question": "Where will this run?",
                    "why_it_matters": "because",
                },
                {
                    "relates_to_field": "accuracy_requirement",
                    "question": "What recall is needed?",
                    "why_it_matters": "because",
                },
            ],
        }

    def test_clarification_uses_flag_answer_without_prompting(self) -> None:
        def unreachable_prompt(msg: str) -> str:
            raise AssertionError("should not prompt: both fields are flag-covered")

        result = _resume_value_for_interrupt(
            self._clarification_payload(),
            answers={"deployment_target": "jetson-orin", "accuracy_requirement": "95%"},
            inputs={},
            approve=False,
            reject=False,
            prompt=unreachable_prompt,
        )
        assert result == {"deployment_target": "jetson-orin", "accuracy_requirement": "95%"}

    def test_clarification_falls_back_to_prompt_for_unflagged_field(self) -> None:
        prompts: list[str] = []

        def prompt(msg: str) -> str:
            prompts.append(msg)
            return "live-answer"

        result = _resume_value_for_interrupt(
            self._clarification_payload(),
            answers={"deployment_target": "jetson-orin"},
            inputs={},
            approve=False,
            reject=False,
            prompt=prompt,
        )
        assert result == {"deployment_target": "jetson-orin", "accuracy_requirement": "live-answer"}
        assert len(prompts) == 1

    def test_clarification_all_blank_or_eof_returns_empty_string_not_empty_dict(self) -> None:
        """Every question declined must resume with `""`, never a literal
        `{}` — ADR-0003 §9 (Q21): `Command(resume={})` is not reliably
        delivered by the installed LangGraph for the clarify interrupt
        (confirmed empirically), so `""` is the only value that actually
        reaches `_node_clarify` and lets the run proceed instead of
        silently re-pausing at the same interrupt forever."""

        def eof_prompt(msg: str) -> str:
            raise EOFError

        result = _resume_value_for_interrupt(
            self._clarification_payload(),
            answers={},
            inputs={},
            approve=False,
            reject=False,
            prompt=eof_prompt,
        )
        assert result == ""

    def _provide_execution_inputs_payload(self) -> dict[str, Any]:
        return {
            "type": "provide_execution_inputs",
            "skill_id": "trt-perf-analysis",
            "binding_id": "trt-perf-analysis-v1",
            "missing_inputs": [
                {"name": "path", "description": "folder path"},
                {"name": "model_name", "description": "model label"},
            ],
        }

    def test_provide_execution_inputs_uses_flag_input_without_prompting(self) -> None:
        result = _resume_value_for_interrupt(
            self._provide_execution_inputs_payload(),
            answers={},
            inputs={"path": "/data/run1", "model_name": "yolov8"},
            approve=False,
            reject=False,
            prompt=lambda msg: (_ for _ in ()).throw(AssertionError("should not prompt")),
        )
        assert result == {"path": "/data/run1", "model_name": "yolov8"}

    def test_provide_execution_inputs_all_blank_returns_empty_string_not_empty_dict(
        self,
    ) -> None:
        """`resume_workflow()`'s own docstring: a literal empty dict is not
        reliably delivered by the installed LangGraph — `""` is the
        documented, correctly-delivered way to signal "declined"."""
        result = _resume_value_for_interrupt(
            self._provide_execution_inputs_payload(),
            answers={},
            inputs={},
            approve=False,
            reject=False,
            prompt=lambda msg: "",
        )
        assert result == ""

    def test_provide_execution_inputs_partial_flag_partial_prompt(self) -> None:
        result = _resume_value_for_interrupt(
            self._provide_execution_inputs_payload(),
            answers={},
            inputs={"path": "/data/run1"},
            approve=False,
            reject=False,
            prompt=lambda msg: "yolov8",
        )
        assert result == {"path": "/data/run1", "model_name": "yolov8"}

    def _approval_payload(self) -> dict[str, Any]:
        return {
            "type": "approval",
            "skill_id": "trt-perf-analysis",
            "binding_id": "trt-perf-analysis-v1",
            "task": "bench it",
            "inputs": {},
        }

    def test_approval_flag_approve_wins_without_prompting(self) -> None:
        result = _resume_value_for_interrupt(
            self._approval_payload(),
            answers={},
            inputs={},
            approve=True,
            reject=False,
            prompt=lambda msg: (_ for _ in ()).throw(AssertionError("should not prompt")),
        )
        assert result == "approved"

    def test_approval_flag_reject_wins_without_prompting(self) -> None:
        result = _resume_value_for_interrupt(
            self._approval_payload(),
            answers={},
            inputs={},
            approve=False,
            reject=True,
            prompt=lambda msg: (_ for _ in ()).throw(AssertionError("should not prompt")),
        )
        assert result == "rejected"

    @pytest.mark.parametrize("answer,expected", [("y", "approved"), ("yes", "approved"),
                                                  ("YES", "approved"), ("n", "rejected"),
                                                  ("", "rejected")])
    def test_approval_live_prompt_answer(self, answer: str, expected: str) -> None:
        result = _resume_value_for_interrupt(
            self._approval_payload(),
            answers={},
            inputs={},
            approve=False,
            reject=False,
            prompt=lambda msg: answer,
        )
        assert result == expected

    def test_approval_eof_prompt_is_rejected_never_silently_approved(self) -> None:
        def eof_prompt(msg: str) -> str:
            raise EOFError

        result = _resume_value_for_interrupt(
            self._approval_payload(),
            answers={},
            inputs={},
            approve=False,
            reject=False,
            prompt=eof_prompt,
        )
        assert result == "rejected"

    def test_unrecognized_interrupt_type_raises(self) -> None:
        with pytest.raises(ValueError):
            _resume_value_for_interrupt(
                {"type": "something_new"},
                answers={},
                inputs={},
                approve=False,
                reject=False,
                prompt=lambda msg: "",
            )


class _FakeInterrupt:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value


class _StuckAgent:
    """Never advances past its one clarification interrupt — reproduces
    the *symptom* of `cv_agent/graph/workflow.py`'s own pre-existing
    `_route_after_analysis` truthiness gap without depending on the real
    graph, so this test is fast and deterministic."""

    def __init__(self) -> None:
        self.resume_calls = 0

    def _state(self) -> dict[str, Any]:
        return {
            "__interrupt__": [
                _FakeInterrupt(
                    {
                        "type": "clarification",
                        "questions": [
                            {
                                "relates_to_field": "x",
                                "question": "?",
                                "why_it_matters": "?",
                            }
                        ],
                    }
                )
            ]
        }

    def start_workflow(self, task, *, session_id, execution_inputs=None):
        return self._state()

    def resume_workflow(self, session_id, resume_value):
        self.resume_calls += 1
        return self._state()


class TestRunWorkflowInteractiveStuckGuard:
    def test_raises_workflow_stuck_error_instead_of_hanging_forever(self) -> None:
        agent = _StuckAgent()
        with pytest.raises(WorkflowStuckError):
            _run_workflow_interactive(
                agent,
                "task",
                "sid",
                answers={},
                inputs={},
                approve=False,
                reject=False,
                prompt=lambda msg: "",
                out=lambda msg: None,
            )
        # Exactly _MAX_INTERRUPT_ROUNDS resumes are attempted before the
        # (_MAX_INTERRUPT_ROUNDS + 1)-th interrupt trips the guard.
        assert agent.resume_calls == _MAX_INTERRUPT_ROUNDS


def _write_fixture_skill(root: Path, skill_id: str, description: str) -> None:
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill_id}\ndescription: {description}\n---\n", encoding="utf-8"
    )


_PLANNING_SKILL_DESCRIPTION = "TensorRT performance benchmarking and layer analysis tool."

_PLANNING_TASK = (
    "Detect intruders using our 8 outdoor CCTV cameras at 1080p/15fps, "
    "deploy on a Jetson Orin, need real-time response with recall above 95%, "
    "and we have 2000 labeled clips already. Also evaluate deployment "
    "optimization performance benchmarking of the model."
)
"""Fully-specified (no clarification questions — verified empirically in
tests/test_workflow.py) plus benchmarking vocabulary matching the fixture
skill's description, so plan_execution is reached directly."""

_VAGUE_PLANNING_TASK = (
    "Detect escape attempts. Also evaluate deployment optimization "
    "performance benchmarking of the model."
)
"""Same benchmarking-vocabulary/fixture-skill match as _PLANNING_TASK, but
missing environment/camera/deployment-target/latency/accuracy/data fields,
so it raises a real clarify interrupt first (field names verified directly
against RequirementsAnalyzer: environment_context, camera_data,
latency_requirement, accuracy_requirement, data_availability)."""


@dataclass
class _FakeRuntime:
    runtime_id: str = "fake-runtime"
    outcome: RuntimeOutcome | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def invoke(self, skill, request):
        self.calls.append((skill.skill_id, dict(request.inputs)))
        assert self.outcome is not None
        return self.outcome


class _GraphAgent:
    """Minimal `CVAgent.start_workflow()`/`.resume_workflow()` duck-type
    backed directly by a compiled `build_requirements_workflow_graph()`
    graph (same construction `tests/test_workflow.py` already uses) —
    proves `_run_workflow_interactive` against a real, unfaked graph run
    without needing real skill discovery or `CVAgent`'s own registration
    machinery."""

    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def start_workflow(
        self, task: str, *, session_id: str, execution_inputs: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        initial: dict[str, Any] = {
            "session_id": session_id,
            "task": task,
            "steps": [],
            "requirements_analysis": None,
            "clarification_answers": {},
            "execution_inputs": execution_inputs or {},
            "planning_result": None,
            "execution_input_recovery": None,
            "pending_execution": None,
            "approval_decision": None,
            "execution_result": None,
        }
        cfg = {"configurable": {"thread_id": session_id}}
        return self._graph.invoke(initial, config=cfg)

    def resume_workflow(self, session_id: str, resume_value: Any) -> dict[str, Any]:
        cfg = {"configurable": {"thread_id": session_id}}
        return self._graph.invoke(Command(resume=resume_value), config=cfg)


def _build_graph(
    tmp_path: Path,
    execution_registry: ExecutionBindingRegistry,
    *,
    skill_id: str = "trt-perf-analysis",
    approval_policy: str = "approval_required",
    input_schema: tuple[InputField, ...] = (
        InputField(name="path", required=True, description="folder path"),
        InputField(name="model_name", required=True, description="model label"),
    ),
    binding_description: str = "",
) -> Any:
    _write_fixture_skill(tmp_path, skill_id, _PLANNING_SKILL_DESCRIPTION)
    executor = SkillExecutor(execution_registry)
    rt = _FakeRuntime(
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
            description=binding_description,
        )
    )
    skill_inventory = SkillInventory(
        sources=(LocalSkillSource(roots=(tmp_path,)),), is_executable=executor.can_execute
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


class TestRunWorkflowInteractiveFixtureGraph:
    """Real graph, synthetic fixture binding (no real installed skill has a
    required input or an approval_required policy — Q20/STATUS.md's own
    documented reason). Proves `_run_workflow_interactive` actually drives
    `provide_execution_inputs` and `approval_gate`, which no CLI-as-
    subprocess test can reach through `_cmd_workflow`'s deliberately
    unregistered `CVAgent`."""

    def test_full_multi_round_run_clarify_then_recovery_then_approval(
        self, tmp_path: Path
    ) -> None:
        """All three interrupt kinds in one single run: clarify (answered
        via --answer-equivalent `answers`), provide_execution_inputs
        (answered partly via --input-equivalent `inputs` — "path" is
        pre-supplied and therefore never even asked about, "model_name" is
        not, so the recovery round asks only for it, answered via a live
        prompt), approval_gate (answered via --approve)."""
        execution_registry = ExecutionBindingRegistry()
        graph = _build_graph(tmp_path, execution_registry)
        agent = _GraphAgent(graph)

        out_lines: list[str] = []
        state = _run_workflow_interactive(
            agent,
            _VAGUE_PLANNING_TASK,
            "multi-round-1",
            answers={"accuracy_requirement": "recall above 95%"},
            inputs={"path": "/data/run1"},
            approve=True,
            reject=False,
            prompt=lambda msg: "yolov8",
            out=out_lines.append,
        )

        assert state["status"] == "done"
        assert state["execution_input_recovery"]["outcome"] == "supplied"
        assert state["execution_input_recovery"]["terminal"] is False
        assert state["approval_decision"] == "approved"
        assert state["execution_result"]["status"] == "completed"
        assert any("[INTERRUPT] clarification" in line for line in out_lines)
        assert any("[INTERRUPT] provide_execution_inputs" in line for line in out_lines)
        assert any("[INTERRUPT] approval" in line for line in out_lines)

    def test_terminal_recovery_outcome_never_reaches_approval_gate(
        self, tmp_path: Path
    ) -> None:
        """A provide_execution_inputs round left entirely blank is a
        terminal "cancelled" outcome — the run must finish without ever
        raising an approval interrupt, per ADR-0010 §13."""
        execution_registry = ExecutionBindingRegistry()
        graph = _build_graph(tmp_path, execution_registry)
        agent = _GraphAgent(graph)

        state = _run_workflow_interactive(
            agent,
            _PLANNING_TASK,
            "terminal-1",
            answers={},
            inputs={},
            approve=False,
            reject=False,
            prompt=lambda msg: "",
            out=lambda msg: None,
        )

        assert state["status"] == "done"
        assert state["execution_input_recovery"]["outcome"] == "cancelled"
        assert state["execution_input_recovery"]["terminal"] is True
        assert state["approval_decision"] is None
        assert state["execution_result"] is None

    def test_approval_gate_rejected_via_reject_flag(self, tmp_path: Path) -> None:
        """Both required inputs pre-supplied (no recovery round needed) so
        this test isolates approval_gate's own reject path. SkillExecutor
        (ADR-0009) still runs `execute` on a rejected decision — it is what
        actually enforces the rejection (D-013) — so `execution_result` is
        populated with status "rejected", not `None`."""
        execution_registry = ExecutionBindingRegistry()
        graph = _build_graph(tmp_path, execution_registry)
        agent = _GraphAgent(graph)

        state = _run_workflow_interactive(
            agent,
            _PLANNING_TASK,
            "reject-1",
            answers={},
            inputs={"path": "/data/run1", "model_name": "yolov8"},
            approve=False,
            reject=True,
            prompt=lambda msg: "",
            out=lambda msg: None,
        )

        assert state["execution_input_recovery"] is None
        assert state["approval_decision"] == "rejected"
        assert state["execution_result"]["status"] == "rejected"


class TestPrintWorkflowSummary:
    def test_reports_terminal_recovery_reason(self) -> None:
        lines: list[str] = []
        _print_workflow_summary(
            {
                "status": "done",
                "steps": [{"node": "plan_execution", "action": "x"}],
                "execution_input_recovery": {
                    "outcome": "binding_mismatch",
                    "terminal": True,
                    "mismatch_detail": "schema_changed",
                },
            },
            out=lines.append,
        )
        joined = "\n".join(lines)
        assert "outcome=binding_mismatch" in joined
        assert "terminal=True" in joined
        assert "detail=schema_changed" in joined

    def test_no_recovery_key_prints_no_recovery_line(self) -> None:
        lines: list[str] = []
        _print_workflow_summary({"status": "done", "steps": []}, out=lines.append)
        assert not any("Execution-input recovery" in line for line in lines)


def _build_two_candidate_graph(tmp_path: Path) -> tuple[Any, list[_FakeRuntime]]:
    """Two individually-verified, executable, `allowed` bindings matching the
    same task — the ADR-0010 §16 (Q18) ambiguous-candidates scenario."""
    execution_registry = ExecutionBindingRegistry()
    runtimes: list[_FakeRuntime] = []
    for skill_id, desc in (
        ("bench-tool-b", "Generic benchmark tool"),
        ("trt-perf-analysis", "TensorRT layer analysis"),
    ):
        _write_fixture_skill(tmp_path, skill_id, _PLANNING_SKILL_DESCRIPTION)
        rt = _FakeRuntime(
            runtime_id=f"fake-runtime-{skill_id}",
            outcome=RuntimeOutcome(success=True, output={"ok": True}),
        )
        runtimes.append(rt)
        execution_registry.register_runtime(rt)
        execution_registry.register_binding(
            ExecutionBinding(
                skill_id=skill_id,
                binding_id=f"{skill_id}-v1",
                runtime_id=rt.runtime_id,
                approval_policy="allowed",
                verified=True,
                description=desc,
            )
        )
    executor = SkillExecutor(execution_registry)
    skill_inventory = SkillInventory(
        sources=(LocalSkillSource(roots=(tmp_path,)),), is_executable=executor.can_execute
    )
    registry = CapabilityRegistry(_REGISTRY_PATH)
    registry.load()
    task_resolver = TaskResolver(capability_registry=registry, skill_inventory=skill_inventory)
    graph = build_requirements_workflow_graph(
        requirements_analyzer=RequirementsAnalyzer(task_resolver=task_resolver, llm=None),
        executor=executor,
        skill_inventory=skill_inventory,
        execution_registry=execution_registry,
        checkpointer=MemorySaver(),
    )
    return graph, runtimes


class TestChooseCandidateCli:
    """ADR-0010 §16 (Q18): `choose_candidate` through the CLI layer. The
    owner chose an interrupt over a `--skill` override, so there is
    deliberately no flag — the human is always asked."""

    _PAYLOAD = {
        "type": "choose_candidate",
        "candidates": [
            {"skill_id": "bench-tool-b", "description": "Generic benchmark tool"},
            {"skill_id": "trt-perf-analysis", "description": "TensorRT layer analysis"},
        ],
    }

    def _resume(self, prompt: Any) -> Any:
        return _resume_value_for_interrupt(
            self._PAYLOAD, answers={}, inputs={}, approve=False, reject=False, prompt=prompt
        )

    def test_prompt_lists_every_candidate_id_and_description_and_returns_the_answer(
        self,
    ) -> None:
        seen: list[str] = []

        def prompt(msg: str) -> str:
            seen.append(msg)
            return "  trt-perf-analysis  "

        assert self._resume(prompt) == "trt-perf-analysis"
        assert len(seen) == 1
        for expected in ("bench-tool-b", "Generic benchmark tool", "trt-perf-analysis",
                         "TensorRT layer analysis"):
            assert expected in seen[0]

    def test_eof_or_blank_returns_empty_string_never_a_default_candidate(self) -> None:
        def eof(msg: str) -> str:
            raise EOFError

        assert self._resume(eof) == ""
        assert self._resume(lambda msg: "   ") == ""

    def test_approve_flag_does_not_answer_a_candidate_prompt(self) -> None:
        """--approve is for approval_gate only; it must never be read as a
        candidate choice (nor as consent to pick one)."""
        answer = _resume_value_for_interrupt(
            self._PAYLOAD,
            answers={},
            inputs={},
            approve=True,
            reject=False,
            prompt=lambda msg: "",
        )
        assert answer == ""

    def test_full_run_asks_then_executes_only_the_chosen_skill(self, tmp_path: Path) -> None:
        graph, (rt_b, rt_trt) = _build_two_candidate_graph(tmp_path)
        out_lines: list[str] = []

        state = _run_workflow_interactive(
            _GraphAgent(graph),
            _PLANNING_TASK,
            "cand-cli-1",
            answers={},
            inputs={},
            approve=False,
            reject=False,
            prompt=lambda msg: "bench-tool-b",
            out=out_lines.append,
        )

        assert state["status"] == "done"
        assert state["candidate_selection"]["outcome"] == "selected"
        assert state["execution_result"]["status"] == "completed"
        assert [c[0] for c in rt_b.calls] == ["bench-tool-b"]
        assert rt_trt.calls == []
        assert any("[INTERRUPT] choose_candidate" in line for line in out_lines)
        assert any("candidate: bench-tool-b (Generic benchmark tool)" in line for line in out_lines)
        assert any("[RESUME] choose_candidate -> 'bench-tool-b'" in line for line in out_lines)

    def test_declining_terminates_cleanly_without_executing_anything(
        self, tmp_path: Path
    ) -> None:
        graph, runtimes = _build_two_candidate_graph(tmp_path)

        state = _run_workflow_interactive(
            _GraphAgent(graph),
            _PLANNING_TASK,
            "cand-cli-2",
            answers={},
            inputs={},
            approve=False,
            reject=False,
            prompt=lambda msg: "",
            out=lambda msg: None,
        )

        assert state["status"] == "done"
        assert state["candidate_selection"]["outcome"] == "cancelled"
        assert state["candidate_selection"]["terminal"] is True
        assert state["execution_result"] is None
        assert all(rt.calls == [] for rt in runtimes)

    def test_summary_reports_the_candidate_selection_outcome(self) -> None:
        lines: list[str] = []
        _print_workflow_summary(
            {
                "status": "done",
                "steps": [],
                "candidate_selection": {
                    "outcome": "invalid",
                    "terminal": True,
                    "chosen_skill_id": None,
                },
            },
            out=lines.append,
        )
        assert any(
            "Candidate selection: outcome=invalid terminal=True chosen=None" in line
            for line in lines
        )


class TestApprovalPromptContext:
    """Issue #47: the `workflow` approval prompt and the `[INTERRUPT] approval`
    echo show the runtime and description carried by the pinned approval payload
    (ADR-0003 section 10.2). Display only - the payload and decisions are unchanged."""

    _PAYLOAD: dict[str, Any] = {
        "type": "approval",
        "skill_id": "trt-perf-analysis",
        "binding_id": "trt-perf-analysis-v1",
        "runtime_id": "fake-runtime-trt-perf-analysis",
        "description": "Layer timing analysis",
        "task": "bench it",
        "inputs": {},
    }

    @staticmethod
    def _ask(payload: dict[str, Any]) -> str:
        seen: list[str] = []

        def prompt(msg: str) -> str:
            seen.append(msg)
            return "n"

        value = _resume_value_for_interrupt(
            payload, answers={}, inputs={}, approve=False, reject=False, prompt=prompt
        )
        assert value == "rejected" and len(seen) == 1
        return seen[0]

    def test_prompt_shows_runtime_and_description_from_the_payload(self) -> None:
        assert self._ask(self._PAYLOAD) == (
            "Approval required for skill 'trt-perf-analysis' via binding "
            "'trt-perf-analysis-v1' "
            "(runtime='fake-runtime-trt-perf-analysis', policy=approval_required, "
            "description='Layer timing analysis'). Approve execution? [y/N]: "
        )

    @pytest.mark.parametrize("empty", ["", "  ", None])
    def test_empty_description_renders_as_no_description(self, empty: Any) -> None:
        msg = self._ask({**self._PAYLOAD, "description": empty})
        assert msg == (
            "Approval required for skill 'trt-perf-analysis' via binding "
            "'trt-perf-analysis-v1' "
            "(runtime='fake-runtime-trt-perf-analysis', policy=approval_required, "
            "description=(no description)). Approve execution? [y/N]: "
        )
        assert "None" not in msg

    def test_payload_without_the_new_keys_does_not_crash(self) -> None:
        legacy = {k: v for k, v in self._PAYLOAD.items() if k not in ("runtime_id", "description")}
        assert self._ask(legacy) == (
            "Approval required for skill 'trt-perf-analysis' via binding "
            "'trt-perf-analysis-v1' (runtime=(unknown), policy=approval_required, "
            "description=(no description)). Approve execution? [y/N]: "
        )

    def test_flags_still_decide_without_prompting(self) -> None:
        def unreachable(msg: str) -> str:
            raise AssertionError("must not prompt")

        for approve, reject, expected in ((True, False, "approved"), (False, True, "rejected")):
            assert (
                _resume_value_for_interrupt(
                    self._PAYLOAD, answers={}, inputs={}, approve=approve, reject=reject,
                    prompt=unreachable,
                )
                == expected
            )

    def test_real_pinned_payload_end_to_end_prompt_and_echo(self, tmp_path: Path) -> None:
        """Through the real graph: the payload comes from the pin, so the human
        sees the runtime/description the approval is bound to."""
        registry = ExecutionBindingRegistry()
        graph = _build_graph(tmp_path, registry, binding_description="Layer timing analysis")
        out_lines: list[str] = []
        prompts: list[str] = []

        def prompt(msg: str) -> str:
            prompts.append(msg)
            return "y"

        state = _run_workflow_interactive(
            _GraphAgent(graph),
            _PLANNING_TASK,
            "prompt-ctx-1",
            answers={},
            inputs={"path": "/data/run1", "model_name": "yolov8"},
            approve=False,
            reject=False,
            prompt=prompt,
            out=out_lines.append,
        )

        assert state["approval_decision"] == "approved"  # decision handling unchanged
        assert state["execution_result"]["status"] == "completed"
        assert prompts == [
            "Approval required for skill 'trt-perf-analysis' via binding "
            "'trt-perf-analysis-v1' "
            "(runtime='fake-runtime-trt-perf-analysis', policy=approval_required, "
            "description='Layer timing analysis'). Approve execution? [y/N]: "
        ]
        echo = [line for line in out_lines if line.startswith("  skill=trt-perf-analysis")]
        assert len(echo) == 1
        assert echo[0].startswith(
            "  skill=trt-perf-analysis binding=trt-perf-analysis-v1 "
            "runtime='fake-runtime-trt-perf-analysis' "
            "description='Layer timing analysis' inputs="
        )

    def test_real_pinned_payload_with_an_empty_description_echo(self, tmp_path: Path) -> None:
        registry = ExecutionBindingRegistry()
        graph = _build_graph(tmp_path, registry)  # binding_description defaults to ""
        out_lines: list[str] = []

        _run_workflow_interactive(
            _GraphAgent(graph),
            _PLANNING_TASK,
            "prompt-ctx-2",
            answers={},
            inputs={"path": "/data/run1", "model_name": "yolov8"},
            approve=False,
            reject=True,
            prompt=lambda msg: "",
            out=out_lines.append,
        )

        echo = [line for line in out_lines if line.startswith("  skill=trt-perf-analysis")]
        assert len(echo) == 1
        assert echo[0].startswith(
            "  skill=trt-perf-analysis binding=trt-perf-analysis-v1 "
            "runtime='fake-runtime-trt-perf-analysis' description=(no description) inputs="
        )
