"""
Tests for cv_agent.execution.runtimes.trt_perf_analysis — the first real
ExecutionRuntime binding (ADR-0009 §8).

Three kinds of test here, deliberately kept separate:

1. TestArgvContract / TestSubprocessErrorMapping — pure unit tests of this
   adapter's own plumbing (input -> argv translation, subprocess-outcome ->
   RuntimeOutcome mapping), using a mocked subprocess.run where useful for
   deterministic, non-timing-dependent coverage of error paths. These test
   THIS module's code, never the skill's own behavior, and never need the
   skill installed.
2. TestRegistryAndApprovalWiring — registry/executor/approval-gate
   integration. No installed skill, no subprocess, ever.
3. TestRealInvocation — genuine subprocess invocation of the real,
   installed trt-perf-analysis skill's real scripts/analyze_trt_perf.py.
   Skipped (not faked) when the skill isn't discoverable in this
   environment — this suite never claims something ran when it didn't.

Nothing here uses FakeRuntime — that class (tests/test_execution.py) tests
SkillExecutor's own logic in isolation and is untouched by this file.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from cv_agent.execution.binding import ExecutionBindingRegistry
from cv_agent.execution.executor import SkillExecutor
from cv_agent.execution.models import RuntimeOutcome, SkillExecutionRequest
from cv_agent.execution.runtimes.trt_perf_analysis import (
    BINDING_ID,
    DEFAULT_SKILL_ID,
    RUNTIME_ID,
    TrtPerfAnalysisRuntime,
    build_binding,
    register,
)
from cv_agent.skills.local import LocalSkillSource
from cv_agent.skills.models import Skill
from tests.test_workflow import _without_pin


def _fixture_skill(location: str) -> Skill:
    return Skill(
        skill_id=DEFAULT_SKILL_ID,
        name=DEFAULT_SKILL_ID,
        description="fixture",
        source="fixture",
        location=location,
    )


def _discover_real_skill() -> Skill | None:
    """Looks for the real, actually-installed trt-perf-analysis skill using
    the same default discovery roots CVAgent uses — never assumed present."""
    for skill in LocalSkillSource().discover():
        if skill.skill_id == DEFAULT_SKILL_ID:
            return skill
    return None


_REAL_SKILL = _discover_real_skill()
requires_real_skill = pytest.mark.skipif(
    _REAL_SKILL is None,
    reason="trt-perf-analysis is not installed under ~/.claude/skills or "
    "~/.agents/skills on this machine — real-invocation tests are skipped, "
    "not faked.",
)


def _write_valid_layers_fixture(folder: Path, label: str = "test") -> None:
    """A minimal, structurally-valid layers_*.json — three chained
    Convolution/Activation layers with well-formed tensors, enough to pass
    scripts/trt_perf/data.py::validate_layers() and produce a real
    layer_only analysis. Built here from the validation rules read directly
    out of the real script, not copied from the skill."""
    layers = [
        {
            "Name": "conv1",
            "LayerType": "Convolution",
            "Inputs": [
                {"Name": "input", "Dimensions": [1, 3, 224, 224], "Format/Datatype": "Float"}
            ],
            "Outputs": [
                {"Name": "conv1_out", "Dimensions": [1, 64, 112, 112], "Format/Datatype": "Float"}
            ],
        },
        {
            "Name": "relu1",
            "LayerType": "Activation",
            "Inputs": [
                {"Name": "conv1_out", "Dimensions": [1, 64, 112, 112], "Format/Datatype": "Float"}
            ],
            "Outputs": [
                {"Name": "relu1_out", "Dimensions": [1, 64, 112, 112], "Format/Datatype": "Float"}
            ],
        },
        {
            "Name": "conv2",
            "LayerType": "Convolution",
            "Inputs": [
                {"Name": "relu1_out", "Dimensions": [1, 64, 112, 112], "Format/Datatype": "Float"}
            ],
            "Outputs": [
                {"Name": "output", "Dimensions": [1, 128, 56, 56], "Format/Datatype": "Float"}
            ],
        },
    ]
    (folder / f"layers_{label}.json").write_text(json.dumps(layers), encoding="utf-8")


class TestArgvContract:
    """Pure unit tests of input -> real CLI argv translation. No
    subprocess, no installed skill required."""

    def test_path_input_produces_positional_argv(self, tmp_path: Path) -> None:
        script = tmp_path / "analyze_trt_perf.py"
        argv = TrtPerfAnalysisRuntime._build_argv(script, {"path": str(tmp_path)})
        assert argv == [str(script), str(tmp_path.resolve())]

    def test_data_input_produces_data_flags(self, tmp_path: Path) -> None:
        script = tmp_path / "analyze_trt_perf.py"
        layer = tmp_path / "layers_a.json"
        profile = tmp_path / "profile_a.json"
        argv = TrtPerfAnalysisRuntime._build_argv(script, {"data": [[str(layer), str(profile)]]})
        assert argv == [str(script), "--data", str(layer.resolve()), str(profile.resolve())]

    def test_data_input_supports_layer_only_spec(self, tmp_path: Path) -> None:
        script = tmp_path / "analyze_trt_perf.py"
        layer = tmp_path / "layers_a.json"
        argv = TrtPerfAnalysisRuntime._build_argv(script, {"data": [[str(layer)]]})
        assert argv == [str(script), "--data", str(layer.resolve())]

    def test_model_name_forwarded(self, tmp_path: Path) -> None:
        script = tmp_path / "analyze_trt_perf.py"
        argv = TrtPerfAnalysisRuntime._build_argv(
            script, {"path": str(tmp_path), "model_name": "my-model"}
        )
        assert argv[-2:] == ["--model-name", "my-model"]

    def test_missing_path_and_data_raises(self, tmp_path: Path) -> None:
        script = tmp_path / "analyze_trt_perf.py"
        with pytest.raises(ValueError, match="requires either"):
            TrtPerfAnalysisRuntime._build_argv(script, {})

    def test_both_path_and_data_raises(self, tmp_path: Path) -> None:
        script = tmp_path / "analyze_trt_perf.py"
        with pytest.raises(ValueError, match="not both"):
            TrtPerfAnalysisRuntime._build_argv(
                script, {"path": str(tmp_path), "data": [[str(tmp_path)]]}
            )

    def test_empty_data_list_raises(self, tmp_path: Path) -> None:
        script = tmp_path / "analyze_trt_perf.py"
        with pytest.raises(ValueError, match="non-empty list"):
            TrtPerfAnalysisRuntime._build_argv(script, {"data": []})

    def test_never_forwards_output_flag(self, tmp_path: Path) -> None:
        """--output is never forwarded, even if a caller sneaks it into
        inputs — this adapter always reads the result from stdout, keeping
        invocation read-only regardless of caller input."""
        script = tmp_path / "analyze_trt_perf.py"
        argv = TrtPerfAnalysisRuntime._build_argv(
            script, {"path": str(tmp_path), "output": str(tmp_path / "out.json")}
        )
        assert "--output" not in argv


class TestSubprocessErrorMapping:
    """Deterministic unit tests of invoke()'s own error handling, via a
    mocked subprocess.run — no timing races, no installed-skill dependency.
    These test this adapter's plumbing, not the skill's behavior (that is
    covered by the real, unmocked tests in TestRealInvocation below)."""

    def _skill_with_script(self, tmp_path: Path) -> Skill:
        skill_dir = tmp_path / "trt-perf-analysis"
        (skill_dir / "scripts").mkdir(parents=True)
        (skill_dir / "scripts" / "analyze_trt_perf.py").write_text("", encoding="utf-8")
        return _fixture_skill(str(skill_dir / "SKILL.md"))

    def test_missing_script_reported_without_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        def _fail_if_called(*args: object, **kwargs: object) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(subprocess, "run", _fail_if_called)
        runtime = TrtPerfAnalysisRuntime()
        skill = _fixture_skill(str(tmp_path / "nonexistent" / "SKILL.md"))

        outcome = runtime.invoke(skill, SkillExecutionRequest(inputs={"path": str(tmp_path)}))

        assert outcome.success is False
        assert outcome.error_message is not None
        assert "not found" in outcome.error_message.lower()
        assert called is False

    def test_timeout_reported_as_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        skill = self._skill_with_script(tmp_path)

        def _raise_timeout(*args: object, **kwargs: object):
            raise subprocess.TimeoutExpired(cmd="analyze_trt_perf.py", timeout=0.001)

        monkeypatch.setattr(subprocess, "run", _raise_timeout)
        runtime = TrtPerfAnalysisRuntime(timeout_seconds=0.001)

        outcome = runtime.invoke(skill, SkillExecutionRequest(inputs={"path": str(tmp_path)}))

        assert outcome.success is False
        assert outcome.error_message is not None
        assert "timed out" in outcome.error_message.lower()

    def test_missing_interpreter_reported_as_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        skill = self._skill_with_script(tmp_path)

        def _raise_oserror(*args: object, **kwargs: object):
            raise OSError("no such file or directory: python")

        monkeypatch.setattr(subprocess, "run", _raise_oserror)
        runtime = TrtPerfAnalysisRuntime()

        outcome = runtime.invoke(skill, SkillExecutionRequest(inputs={"path": str(tmp_path)}))

        assert outcome.success is False
        assert outcome.error_message is not None
        assert "unable to launch" in outcome.error_message.lower()

    def test_nonzero_exit_reports_stderr_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        skill = self._skill_with_script(tmp_path)

        def _fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(
                args=[], returncode=2, stdout="", stderr="error: No layers found.\n"
            )

        monkeypatch.setattr(subprocess, "run", _fake_run)
        runtime = TrtPerfAnalysisRuntime()

        outcome = runtime.invoke(skill, SkillExecutionRequest(inputs={"path": str(tmp_path)}))

        assert outcome.success is False
        assert outcome.error_message == "error: No layers found."

    def test_non_json_stdout_reported_as_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        skill = self._skill_with_script(tmp_path)

        def _fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="not json at all", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", _fake_run)
        runtime = TrtPerfAnalysisRuntime()

        outcome = runtime.invoke(skill, SkillExecutionRequest(inputs={"path": str(tmp_path)}))

        assert outcome.success is False
        assert outcome.error_message is not None
        assert "non-json" in outcome.error_message.lower()

    def test_json_array_stdout_is_not_treated_as_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The real script always emits a JSON object, never a bare array —
        this guards against silently accepting the wrong shape."""
        skill = self._skill_with_script(tmp_path)

        def _fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="[1, 2, 3]", stderr="")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        runtime = TrtPerfAnalysisRuntime()

        outcome = runtime.invoke(skill, SkillExecutionRequest(inputs={"path": str(tmp_path)}))

        assert outcome.success is False

    def test_successful_mocked_json_is_returned_verbatim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        skill = self._skill_with_script(tmp_path)
        payload = {"schema_version": "1.0", "results": []}

        def _fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(payload), stderr=""
            )

        monkeypatch.setattr(subprocess, "run", _fake_run)
        runtime = TrtPerfAnalysisRuntime()

        outcome = runtime.invoke(skill, SkillExecutionRequest(inputs={"path": str(tmp_path)}))

        assert outcome.success is True
        assert outcome.output == payload


class TestRegistryAndApprovalWiring:
    """Registry/executor/approval integration — needs no installed skill or
    subprocess; exercises the same SkillExecutor path a real run would."""

    def test_build_binding_is_verified_and_scoped_to_one_skill(self) -> None:
        binding = build_binding()
        assert binding.skill_id == DEFAULT_SKILL_ID
        assert binding.binding_id == BINDING_ID
        assert binding.runtime_id == RUNTIME_ID
        assert binding.verified is True
        assert binding.approval_policy == "allowed"

    def test_build_binding_declares_the_real_path_data_xor_contract(self) -> None:
        """ADR-0009 §12 (Q20): the real input_schema/input_field_groups now
        match _build_argv()'s actual contract — path/data each optional
        individually, grouped as exactly_one; model_name genuinely optional,
        no group."""
        binding = build_binding()

        by_name = {f.name: f for f in binding.input_schema}
        assert set(by_name) == {"path", "data", "model_name"}
        assert by_name["path"].required is False
        assert by_name["data"].required is False
        assert by_name["model_name"].required is False

        assert len(binding.input_field_groups) == 1
        group = binding.input_field_groups[0]
        assert group.kind == "exactly_one"
        assert group.field_names == ("path", "data")

    def test_register_makes_skill_executable_through_executor(self) -> None:
        registry = ExecutionBindingRegistry()
        register(registry)
        executor = SkillExecutor(registry)

        assert executor.can_execute(DEFAULT_SKILL_ID) is True
        assert [b.skill_id for b in registry.list_bindings()] == [DEFAULT_SKILL_ID]
        assert [r.runtime_id for r in registry.list_runtimes()] == [RUNTIME_ID]

    def test_registering_does_not_affect_other_skills(self) -> None:
        registry = ExecutionBindingRegistry()
        register(registry)
        executor = SkillExecutor(registry)

        assert executor.can_execute("some-other-skill") is False

    def test_fresh_cvagent_registry_is_still_empty_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """register() is opt-in, never automatic — ADR-0009 §3's "no
        binding registered anywhere in this codebase by default" must still
        hold for a plain CVAgent() after this module exists."""
        monkeypatch.setenv("CV_AGENT_SKILL_PATHS", str(tmp_path))
        from cv_agent.runtime.agent import CVAgent

        agent = CVAgent()
        assert agent.execution_bindings.list_bindings() == []
        assert agent.execution_bindings.list_runtimes() == []

    def test_approval_required_binding_rejects_without_approval_and_never_invokes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry = ExecutionBindingRegistry()
        register(registry, approval_policy="approval_required")
        called = False

        def _fail_if_called(self, skill, request):  # noqa: ANN001
            nonlocal called
            called = True
            return RuntimeOutcome(success=True, output={})

        monkeypatch.setattr(TrtPerfAnalysisRuntime, "invoke", _fail_if_called)
        executor = SkillExecutor(registry)

        result = executor.execute(
            _fixture_skill("/fixtures/trt-perf-analysis/SKILL.md"),
            SkillExecutionRequest(inputs={"path": "/does/not/matter"}),
        )

        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.category == "approval_denied"
        assert called is False

    def test_approval_required_binding_runs_once_approved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proves the approval gate, not the runtime, is what blocked the
        prior test: once approved, SkillExecutor does call through to
        invoke(). The real subprocess path itself is covered separately by
        TestRealInvocation, below."""
        registry = ExecutionBindingRegistry()
        register(registry, approval_policy="approval_required")
        calls: list[str] = []

        def _fake_invoke(self, skill, request):  # noqa: ANN001
            calls.append(skill.skill_id)
            return RuntimeOutcome(success=True, output={"ok": True})

        monkeypatch.setattr(TrtPerfAnalysisRuntime, "invoke", _fake_invoke)
        executor = SkillExecutor(registry)

        result = executor.execute(
            _fixture_skill("/fixtures/trt-perf-analysis/SKILL.md"),
            SkillExecutionRequest(
                inputs={"path": "/does/not/matter"},
                approved=True,
                expected_binding_pin=registry.pin(DEFAULT_SKILL_ID),
            ),
        )

        assert result.status == "completed"
        assert calls == [DEFAULT_SKILL_ID]

    def test_unregistered_skill_stays_not_executable(self) -> None:
        registry = ExecutionBindingRegistry()
        register(registry)
        executor = SkillExecutor(registry)

        result = executor.execute(
            Skill(
                skill_id="never-registered",
                name="never-registered",
                description="",
                source="fixture",
                location="/fixtures/never-registered/SKILL.md",
            ),
            SkillExecutionRequest(),
        )
        assert result.status == "not_executable"


@requires_real_skill
class TestRealInvocation:
    """Genuine subprocess invocation of the real, installed
    trt-perf-analysis skill — no FakeRuntime, no fabricated success. Skipped
    entirely (not faked) on a machine without the skill installed."""

    def test_successful_real_invocation_via_cvagent(self, tmp_path: Path) -> None:
        """The end-to-end path the task asked to demonstrate: CVAgent
        discovers the real skill, the binding is registered explicitly
        (never automatic), and CVAgent.execute() — not the adapter called
        directly — drives the real script and returns its real,
        deterministic output."""
        from cv_agent.runtime.agent import CVAgent

        _write_valid_layers_fixture(tmp_path)
        agent = CVAgent()

        skill = agent.skills.get(DEFAULT_SKILL_ID)
        assert skill is not None, "real trt-perf-analysis must be genuinely discovered"

        register(agent.execution_bindings)
        assert agent.can_execute(DEFAULT_SKILL_ID) is True

        result = agent.execute(
            skill, SkillExecutionRequest(inputs={"path": str(tmp_path)}, task="smoke test")
        )

        assert result.status == "completed"
        assert result.ok is True
        assert result.output is not None
        assert result.output["schema_version"] == "1.0"
        assert result.output["validation"]["status"] == "passed"
        assert result.output["results"][0]["layer_count"] == 3
        assert result.evidence.binding_id == BINDING_ID
        assert result.evidence.runtime_id == RUNTIME_ID
        assert result.evidence.started_at is not None
        assert result.evidence.completed_at is not None

    def test_deterministic_output_is_stable_across_repeated_real_runs(
        self, tmp_path: Path
    ) -> None:
        _write_valid_layers_fixture(tmp_path)
        runtime = TrtPerfAnalysisRuntime()
        request = SkillExecutionRequest(inputs={"path": str(tmp_path)})

        first = runtime.invoke(_REAL_SKILL, request)
        second = runtime.invoke(_REAL_SKILL, request)

        assert first.success is True
        assert second.success is True
        assert first.output["schema_version"] == second.output["schema_version"]
        assert first.output["validation"] == second.output["validation"]
        assert first.output["results"] == second.output["results"]

    def test_real_execution_failure_on_empty_folder(self, tmp_path: Path) -> None:
        """No layers_*.json/profile_*.json present — the real script's own
        documented failure path (verified manually against the real script:
        exit code 2, a one-line stderr message), not a simulated error."""
        runtime = TrtPerfAnalysisRuntime()

        outcome = runtime.invoke(
            _REAL_SKILL, SkillExecutionRequest(inputs={"path": str(tmp_path)})
        )

        assert outcome.success is False
        assert outcome.error_message is not None
        assert "layers" in outcome.error_message.lower()

    def test_real_execution_failure_surfaces_through_skill_executor(
        self, tmp_path: Path
    ) -> None:
        registry = ExecutionBindingRegistry()
        register(registry)
        executor = SkillExecutor(registry)

        result = executor.execute(
            _REAL_SKILL, SkillExecutionRequest(inputs={"path": str(tmp_path)})
        )

        assert result.status == "failed"
        assert result.error is not None
        assert result.error.category == "runtime_error"

    def test_malformed_backend_json_is_reported_inside_a_successful_response(
        self, tmp_path: Path
    ) -> None:
        """Verified against the real script's actual behavior (not assumed):
        invalid JSON in one layers_*.json does NOT crash the process — the
        script's own contract is "exit 0 whenever structured data can be
        emitted at all," so a malformed backend is reported as a failed
        entry inside a still-successful (exit 0, valid JSON) response. Only
        a folder with no backend files at all (see
        test_real_execution_failure_on_empty_folder) hits the process-level
        failure path."""
        (tmp_path / "layers_bad.json").write_text("{not valid json", encoding="utf-8")
        runtime = TrtPerfAnalysisRuntime()

        outcome = runtime.invoke(
            _REAL_SKILL, SkillExecutionRequest(inputs={"path": str(tmp_path)})
        )

        assert outcome.success is True
        assert outcome.output["validation"]["status"] == "failed"
        assert outcome.output["validation"]["failed_count"] == 1


_TRT_PERF_WORKFLOW_REQUEST = (
    "Detect intruders using our 8 outdoor CCTV cameras at 1080p/15fps, "
    "deploy on a Jetson Orin, need real-time response with recall above 95%, "
    "and we have 2000 labeled clips already. Also evaluate deployment "
    "optimization performance benchmarking of the model."
)
"""Same wording as tests/test_workflow.py's own _PLANNING_TASK — deliberately
fully-specified (zero clarification questions, verified empirically there)
plus benchmarking/deployment-optimization vocabulary, so this reaches
plan_execution directly through the real workflow graph without an
intervening clarify interrupt."""


@requires_real_skill
class TestRealPlanningAndRecovery:
    """
    Genuine, unfaked end-to-end test of ADR-0010's planning/recovery flow
    against the real, installed trt-perf-analysis binding — the exact
    scenario ADR-0010 §13.8 named as blocked and `docs/state/
    OPEN_QUESTIONS.md` Q20 tracked: build_binding()'s input_schema was
    deliberately left unpopulated because InputField.required alone could
    not express the real path/data XOR contract, so every prior recovery
    test used a synthetic fixture binding with a plain required=True field
    instead. Now that ADR-0009 §12/ADR-0010 §14 add RequiredFieldGroup and
    populate the real schema, this exercises CVAgent.start_workflow()/
    resume_workflow() against the real skill, the real registered binding,
    and a real subprocess invocation — not a fixture, not a mock runtime.
    """

    def test_pre_supplied_path_alone_satisfies_the_real_xor_group_and_executes(
        self, tmp_path: Path
    ) -> None:
        from cv_agent.config.settings import AgentConfig
        from cv_agent.execution.runtimes.trt_perf_analysis import register
        from cv_agent.runtime.agent import CVAgent

        _write_valid_layers_fixture(tmp_path)
        agent = CVAgent(AgentConfig(workspace_root=tmp_path))
        register(agent.execution_bindings)

        result = agent.start_workflow(
            _TRT_PERF_WORKFLOW_REQUEST,
            session_id="q20-presupply",
            execution_inputs={"path": str(tmp_path)},
        )

        assert "__interrupt__" not in result
        planning_result = result["planning_result"]
        assert planning_result is not None
        assert planning_result["status"] == "planned"
        assert _without_pin(result["pending_execution"]) == {
            "skill_id": DEFAULT_SKILL_ID,
            "inputs": {"path": str(tmp_path)},
            "task": _TRT_PERF_WORKFLOW_REQUEST,
        }
        assert result["status"] == "done"
        execution_result = result["execution_result"]
        assert execution_result is not None
        assert execution_result["status"] == "completed"
        assert execution_result["output"]["schema_version"] == "1.0"

    def test_recovery_interrupt_asks_for_the_group_and_supplying_data_alone_recovers(
        self, tmp_path: Path
    ) -> None:
        """No execution_inputs pre-supplied at all -> plan_execution() finds
        the real path/data group entirely unsatisfied -> provide_execution_
        inputs interrupts, naming both path and data (never a composite
        string) -> resuming with only 'data' (the other XOR member) is
        enough to reach status == 'supplied' and a real completed
        execution — proving the group-aware fulfillment check, not just the
        group-aware missing-input detection, works end to end."""
        from cv_agent.config.settings import AgentConfig
        from cv_agent.execution.runtimes.trt_perf_analysis import register
        from cv_agent.runtime.agent import CVAgent

        _write_valid_layers_fixture(tmp_path, label="recovery")
        layers_path = tmp_path / "layers_recovery.json"
        agent = CVAgent(AgentConfig(workspace_root=tmp_path))
        register(agent.execution_bindings)

        paused = agent.start_workflow(
            _TRT_PERF_WORKFLOW_REQUEST, session_id="q20-recovery"
        )

        assert "__interrupt__" in paused
        interrupt_payload = paused["__interrupt__"][0].value
        assert interrupt_payload["type"] == "provide_execution_inputs"
        assert {m["name"] for m in interrupt_payload["missing_inputs"]} == {"path", "data"}
        assert interrupt_payload["field_groups"] == [
            {"kind": "exactly_one", "field_names": ["path", "data"]}
        ]

        resumed = agent.resume_workflow(
            "q20-recovery", {"data": [[str(layers_path)]]}
        )

        assert "__interrupt__" not in resumed
        recovery = resumed["execution_input_recovery"]
        assert recovery is not None
        assert recovery["outcome"] == "supplied"
        assert recovery["terminal"] is False
        assert _without_pin(resumed["pending_execution"]) == {
            "skill_id": DEFAULT_SKILL_ID,
            "inputs": {"data": [[str(layers_path)]]},
            "task": _TRT_PERF_WORKFLOW_REQUEST,
        }
        assert resumed["status"] == "done"
        execution_result = resumed["execution_result"]
        assert execution_result is not None
        assert execution_result["status"] == "completed"
        assert execution_result["output"]["schema_version"] == "1.0"

    def test_pre_supplying_both_path_and_data_together_is_rejected_before_execution(
        self, tmp_path: Path
    ) -> None:
        """ADR-0010 §15 (review correction on PR #40): against the real
        binding, supplying both XOR alternatives together must be caught
        as "conflicting_inputs" and reach status == "done" without the
        real subprocess ever being invoked — no execution_result at all,
        not even a failed one. Deliberately passes no fixture layer file:
        if the runtime were reached despite the conflict, it would either
        crash trying to build conflicting argv or fail on missing input
        files, either of which this test's `execution_result is None`
        assertion would already catch as a false pass without needing to
        inspect *why* it failed."""
        from cv_agent.config.settings import AgentConfig
        from cv_agent.execution.runtimes.trt_perf_analysis import register
        from cv_agent.runtime.agent import CVAgent

        agent = CVAgent(AgentConfig(workspace_root=tmp_path))
        register(agent.execution_bindings)

        result = agent.start_workflow(
            _TRT_PERF_WORKFLOW_REQUEST,
            session_id="q20-conflict-presupply",
            execution_inputs={"path": str(tmp_path), "data": [["layers.json"]]},
        )

        assert "__interrupt__" not in result
        planning_result = result["planning_result"]
        assert planning_result is not None
        assert planning_result["status"] == "conflicting_inputs"
        assert sorted(planning_result["conflicting_inputs"]) == ["data", "path"]
        assert planning_result["plan"] is None
        assert result["pending_execution"] is None
        assert result["approval_decision"] == "not_required"
        assert result["execution_result"] is None
        assert result["status"] == "done"

    def test_recovery_supplying_both_path_and_data_together_is_rejected_before_execution(
        self, tmp_path: Path
    ) -> None:
        """Same real-binding proof via the recovery path: the interrupt
        fires because neither alternative was pre-supplied, and the human
        answers with BOTH at once — must be rejected, never executed."""
        from cv_agent.config.settings import AgentConfig
        from cv_agent.execution.runtimes.trt_perf_analysis import register
        from cv_agent.runtime.agent import CVAgent

        agent = CVAgent(AgentConfig(workspace_root=tmp_path))
        register(agent.execution_bindings)

        paused = agent.start_workflow(
            _TRT_PERF_WORKFLOW_REQUEST, session_id="q20-conflict-recovery"
        )
        assert "__interrupt__" in paused

        resumed = agent.resume_workflow(
            "q20-conflict-recovery",
            {"path": str(tmp_path), "data": [["layers.json"]]},
        )

        assert "__interrupt__" not in resumed
        recovery = resumed["execution_input_recovery"]
        assert recovery is not None
        assert recovery["outcome"] == "conflicting"
        assert recovery["terminal"] is True
        assert resumed["pending_execution"] is None
        assert resumed["execution_result"] is None
        assert resumed["status"] == "done"
