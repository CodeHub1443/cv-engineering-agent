"""
Tests for cv_agent.execution — SkillExecutor, ExecutionBinding,
ExecutionBindingRegistry.

Every test uses fake runtimes/bindings constructed in this file. None depend
on the developer's real ~/.claude/skills or ~/.agents/skills installation.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from cv_agent.execution.binding import (
    ExecutionBinding,
    ExecutionBindingRegistry,
    InputField,
    RequiredFieldGroup,
)
from cv_agent.execution.executor import SkillExecutor
from cv_agent.execution.models import RuntimeOutcome, SkillExecutionRequest
from cv_agent.skills.models import Skill


def _skill(skill_id: str = "fixture-skill") -> Skill:
    return Skill(
        skill_id=skill_id,
        name=skill_id,
        description="A fake test skill.",
        source="fixture",
        location=f"/fixtures/{skill_id}/SKILL.md",
    )


@dataclass
class FakeRuntime:
    """Configurable fake ExecutionRuntime — success, failure, or raise."""

    runtime_id: str = "fake-runtime"
    outcome: RuntimeOutcome | None = None
    raises: Exception | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def invoke(self, skill: Skill, request: SkillExecutionRequest) -> RuntimeOutcome:
        self.calls.append((skill.skill_id, dict(request.inputs)))
        if self.raises is not None:
            raise self.raises
        assert self.outcome is not None
        return self.outcome


def _registry_with(
    binding: ExecutionBinding, runtime: FakeRuntime | None
) -> tuple[ExecutionBindingRegistry, FakeRuntime | None]:
    registry = ExecutionBindingRegistry()
    registry.register_binding(binding)
    if runtime is not None:
        registry.register_runtime(runtime)
    return registry, runtime


class TestNotExecutable:
    def test_discovered_skill_without_binding_is_not_executable(self) -> None:
        registry = ExecutionBindingRegistry()
        executor = SkillExecutor(registry)
        skill = _skill()

        result = executor.execute(skill, SkillExecutionRequest())

        assert result.status == "not_executable"
        assert result.error is not None
        assert result.error.category == "no_binding"
        assert executor.can_execute(skill.skill_id) is False

    def test_unknown_skill_is_not_executable(self) -> None:
        registry = ExecutionBindingRegistry()
        executor = SkillExecutor(registry)

        result = executor.execute(_skill("never-registered"), SkillExecutionRequest())

        assert result.status == "not_executable"
        assert result.skill_id == "never-registered"

    def test_unverified_binding_is_not_executable(self) -> None:
        binding = ExecutionBinding(
            skill_id="fixture-skill",
            binding_id="b1",
            runtime_id="fake-runtime",
            approval_policy="allowed",
            verified=False,
        )
        registry, _ = _registry_with(binding, FakeRuntime())
        executor = SkillExecutor(registry)

        result = executor.execute(_skill(), SkillExecutionRequest())

        assert result.status == "not_executable"
        assert result.error is not None
        assert result.error.category == "binding_not_verified"
        assert executor.can_execute("fixture-skill") is False

    def test_binding_referencing_unregistered_runtime_is_not_executable(self) -> None:
        binding = ExecutionBinding(
            skill_id="fixture-skill",
            binding_id="b1",
            runtime_id="ghost-runtime",
            approval_policy="allowed",
            verified=True,
        )
        registry, _ = _registry_with(binding, runtime=None)
        executor = SkillExecutor(registry)

        result = executor.execute(_skill(), SkillExecutionRequest())

        assert result.status == "not_executable"
        assert result.error is not None
        assert result.error.category == "no_binding"


class TestExecutable:
    def test_verified_binding_with_runtime_is_executable(self) -> None:
        binding = ExecutionBinding(
            skill_id="fixture-skill",
            binding_id="b1",
            runtime_id="fake-runtime",
            approval_policy="allowed",
            verified=True,
        )
        registry, _ = _registry_with(binding, FakeRuntime())
        executor = SkillExecutor(registry)

        assert executor.can_execute("fixture-skill") is True

    def test_execution_success_reports_completed_with_output(self) -> None:
        binding = ExecutionBinding(
            skill_id="fixture-skill",
            binding_id="b1",
            runtime_id="fake-runtime",
            approval_policy="allowed",
            verified=True,
        )
        runtime = FakeRuntime(outcome=RuntimeOutcome(success=True, output={"ok": 1}))
        registry, _ = _registry_with(binding, runtime)
        executor = SkillExecutor(registry)

        result = executor.execute(_skill(), SkillExecutionRequest(inputs={"x": 1}))

        assert result.status == "completed"
        assert result.ok is True
        assert result.output == {"ok": 1}
        assert result.evidence.binding_id == "b1"
        assert result.evidence.runtime_id == "fake-runtime"
        assert result.evidence.started_at is not None
        assert result.evidence.completed_at is not None
        assert runtime.calls == [("fixture-skill", {"x": 1})]

    def test_execution_failure_reports_failed_with_error(self) -> None:
        binding = ExecutionBinding(
            skill_id="fixture-skill",
            binding_id="b1",
            runtime_id="fake-runtime",
            approval_policy="allowed",
            verified=True,
        )
        runtime = FakeRuntime(outcome=RuntimeOutcome(success=False, error_message="boom"))
        registry, _ = _registry_with(binding, runtime)
        executor = SkillExecutor(registry)

        result = executor.execute(_skill(), SkillExecutionRequest())

        assert result.status == "failed"
        assert result.ok is False
        assert result.error is not None
        assert result.error.category == "runtime_error"
        assert result.error.message == "boom"

    def test_runtime_exception_is_caught_and_reported_as_failed(self) -> None:
        binding = ExecutionBinding(
            skill_id="fixture-skill",
            binding_id="b1",
            runtime_id="fake-runtime",
            approval_policy="allowed",
            verified=True,
        )
        runtime = FakeRuntime(raises=RuntimeError("kaboom"))
        registry, _ = _registry_with(binding, runtime)
        executor = SkillExecutor(registry)

        result = executor.execute(_skill(), SkillExecutionRequest())

        assert result.status == "failed"
        assert result.error is not None
        assert result.error.category == "runtime_error"
        assert "kaboom" in result.error.message


class TestApprovalPolicy:
    def test_rejected_policy_is_always_rejected(self) -> None:
        binding = ExecutionBinding(
            skill_id="fixture-skill",
            binding_id="b1",
            runtime_id="fake-runtime",
            approval_policy="rejected",
            verified=True,
        )
        runtime = FakeRuntime(outcome=RuntimeOutcome(success=True))
        registry, _ = _registry_with(binding, runtime)
        executor = SkillExecutor(registry)

        result = executor.execute(_skill(), SkillExecutionRequest(approved=True))

        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.category == "approval_denied"
        assert runtime.calls == []  # never invoked

    def test_approval_required_without_approval_is_rejected(self) -> None:
        binding = ExecutionBinding(
            skill_id="fixture-skill",
            binding_id="b1",
            runtime_id="fake-runtime",
            approval_policy="approval_required",
            verified=True,
        )
        runtime = FakeRuntime(outcome=RuntimeOutcome(success=True))
        registry, _ = _registry_with(binding, runtime)
        executor = SkillExecutor(registry)

        result = executor.execute(_skill(), SkillExecutionRequest(approved=False))

        assert result.status == "rejected"
        assert runtime.calls == []

    def test_approval_required_with_approval_executes(self) -> None:
        binding = ExecutionBinding(
            skill_id="fixture-skill",
            binding_id="b1",
            runtime_id="fake-runtime",
            approval_policy="approval_required",
            verified=True,
        )
        runtime = FakeRuntime(outcome=RuntimeOutcome(success=True, output={}))
        registry, _ = _registry_with(binding, runtime)
        executor = SkillExecutor(registry)

        result = executor.execute(_skill(), SkillExecutionRequest(approved=True))

        assert result.status == "completed"
        assert len(runtime.calls) == 1

    def test_allowed_policy_executes_without_approval(self) -> None:
        binding = ExecutionBinding(
            skill_id="fixture-skill",
            binding_id="b1",
            runtime_id="fake-runtime",
            approval_policy="allowed",
            verified=True,
        )
        runtime = FakeRuntime(outcome=RuntimeOutcome(success=True, output={}))
        registry, _ = _registry_with(binding, runtime)
        executor = SkillExecutor(registry)

        result = executor.execute(_skill(), SkillExecutionRequest(approved=False))

        assert result.status == "completed"


class TestRegistry:
    def test_get_binding_for_missing_skill_returns_none(self) -> None:
        registry = ExecutionBindingRegistry()
        assert registry.get_binding("nope") is None

    def test_get_runtime_for_missing_runtime_returns_none(self) -> None:
        registry = ExecutionBindingRegistry()
        assert registry.get_runtime("nope") is None

    def test_binding_lookup_is_deterministic_across_repeated_calls(self) -> None:
        registry = ExecutionBindingRegistry()
        binding = ExecutionBinding(
            skill_id="fixture-skill",
            binding_id="b1",
            runtime_id="fake-runtime",
            approval_policy="allowed",
            verified=True,
        )
        registry.register_binding(binding)

        results = [registry.get_binding("fixture-skill") for _ in range(5)]
        assert all(r == binding for r in results)

    def test_list_bindings_is_sorted_by_skill_id(self) -> None:
        registry = ExecutionBindingRegistry()
        for skill_id in ("zebra-skill", "alpha-skill", "mid-skill"):
            registry.register_binding(
                ExecutionBinding(
                    skill_id=skill_id,
                    binding_id=f"b-{skill_id}",
                    runtime_id="fake-runtime",
                    approval_policy="allowed",
                    verified=True,
                )
            )

        ordered = [b.skill_id for b in registry.list_bindings()]
        assert ordered == ["alpha-skill", "mid-skill", "zebra-skill"]

    def test_registry_starts_empty_by_default_in_a_fresh_agent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CVAgent must not pre-register any binding — see ADR-0009 §5:
        inspection found no generically-verifiable invocation mechanism."""
        monkeypatch.setenv("CV_AGENT_SKILL_PATHS", str(tmp_path))
        from cv_agent.runtime.agent import CVAgent

        agent = CVAgent()
        assert agent.execution_bindings.list_bindings() == []
        assert agent.execution_bindings.list_runtimes() == []


class TestResolveNeverExecutes:
    def test_resolve_does_not_touch_the_execution_registry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CV_AGENT_SKILL_PATHS", str(tmp_path))
        from cv_agent.runtime.agent import CVAgent

        agent = CVAgent()
        agent.resolve("deploy RT-DETR on Jetson using DeepStream")

        assert agent.execution_bindings.list_bindings() == []

    def test_analyze_requirements_does_not_touch_the_execution_registry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CV_AGENT_SKILL_PATHS", str(tmp_path))
        from cv_agent.runtime.agent import CVAgent

        agent = CVAgent()
        agent.analyze_requirements("I need to detect garment theft in a factory")

        assert agent.execution_bindings.list_bindings() == []


class TestRequiredFieldGroup:
    """ADR-0009 §12 (Q20): RequiredFieldGroup's own shape/validation,
    independent of ExecutionBinding's cross-field checks below."""

    def test_constructs_with_two_field_names(self) -> None:
        group = RequiredFieldGroup(kind="exactly_one", field_names=("path", "data"))
        assert group.kind == "exactly_one"
        assert group.field_names == ("path", "data")
        assert group.description == ""

    def test_is_frozen(self) -> None:
        group = RequiredFieldGroup(kind="exactly_one", field_names=("path", "data"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            group.field_names = ("a", "b")  # type: ignore[misc]

    def test_fewer_than_two_field_names_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least two names"):
            RequiredFieldGroup(kind="exactly_one", field_names=("path",))

    def test_zero_field_names_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least two names"):
            RequiredFieldGroup(kind="exactly_one", field_names=())

    def test_duplicate_field_names_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            RequiredFieldGroup(kind="exactly_one", field_names=("path", "path"))


class TestExecutionBindingFieldGroupValidation:
    """ADR-0009 §12 (Q20): ExecutionBinding.__post_init__ cross-checks
    input_field_groups against input_schema at construction time — a bad
    group is a construction-time error, never a silently-accepted binding
    that only misbehaves later at planning time."""

    def _schema(self) -> tuple[InputField, ...]:
        return (
            InputField(name="path", required=False, description="folder path"),
            InputField(name="data", required=False, description="data list"),
        )

    def test_valid_group_over_declared_optional_fields_constructs_cleanly(self) -> None:
        binding = ExecutionBinding(
            skill_id="fixture-skill",
            binding_id="fixture-skill-v1",
            runtime_id="fixture-runtime",
            approval_policy="allowed",
            verified=True,
            input_schema=self._schema(),
            input_field_groups=(
                RequiredFieldGroup(kind="exactly_one", field_names=("path", "data")),
            ),
        )
        assert len(binding.input_field_groups) == 1

    def test_group_referencing_an_undeclared_field_name_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="undeclared"):
            ExecutionBinding(
                skill_id="fixture-skill",
                binding_id="fixture-skill-v1",
                runtime_id="fixture-runtime",
                approval_policy="allowed",
                verified=True,
                input_schema=self._schema(),
                input_field_groups=(
                    RequiredFieldGroup(kind="exactly_one", field_names=("path", "nonexistent")),
                ),
            )

    def test_group_member_marked_individually_required_is_rejected(self) -> None:
        schema = (
            InputField(name="path", required=True, description="folder path"),
            InputField(name="data", required=False, description="data list"),
        )
        with pytest.raises(ValueError, match="contradictory"):
            ExecutionBinding(
                skill_id="fixture-skill",
                binding_id="fixture-skill-v1",
                runtime_id="fixture-runtime",
                approval_policy="allowed",
                verified=True,
                input_schema=schema,
                input_field_groups=(
                    RequiredFieldGroup(kind="exactly_one", field_names=("path", "data")),
                ),
            )

    def test_defaults_to_empty_tuple(self) -> None:
        binding = ExecutionBinding(
            skill_id="fixture-skill",
            binding_id="fixture-skill-v1",
            runtime_id="fixture-runtime",
            approval_policy="allowed",
            verified=True,
        )
        assert binding.input_field_groups == ()
