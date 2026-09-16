"""
Tests for the ADR-0010 execution-planning contract: ExecutionPlan and
ExecutionBinding.input_schema/InputField.

This ADR ships TYPES ONLY — no selection logic, no graph node, no behavior.
These tests prove the contract is real, constructible Python with exactly
the documented shape, and that the existing ExecutionBinding construction
site (trt_perf_analysis.build_binding()) is unaffected by the new field.
Behavioral tests (selection, input-completeness, graph routing) belong to
the future implementation PR ADR-0010 unblocks, not this one.
"""

from __future__ import annotations

import dataclasses

import pytest

from cv_agent.execution.binding import ExecutionBinding, InputField
from cv_agent.execution.runtimes.trt_perf_analysis import build_binding
from cv_agent.graph.planning import ExecutionPlan


class TestExecutionPlanShape:
    def test_constructs_with_exactly_the_documented_fields(self) -> None:
        plan = ExecutionPlan(
            skill_id="trt-perf-analysis",
            task_component="benchmarking",
            inputs={"path": "/tmp/some-folder"},
            source_task="analyze tensorrt layer performance",
        )
        assert plan.skill_id == "trt-perf-analysis"
        assert plan.task_component == "benchmarking"
        assert plan.inputs == {"path": "/tmp/some-folder"}
        assert plan.source_task == "analyze tensorrt layer performance"

    def test_source_task_may_be_none(self) -> None:
        plan = ExecutionPlan(
            skill_id="trt-perf-analysis",
            task_component="benchmarking",
            inputs={},
            source_task=None,
        )
        assert plan.source_task is None

    def test_is_frozen(self) -> None:
        plan = ExecutionPlan(
            skill_id="trt-perf-analysis",
            task_component="benchmarking",
            inputs={},
            source_task=None,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.skill_id = "something-else"  # type: ignore[misc]

    def test_field_names_match_the_adr_exactly(self) -> None:
        field_names = {f.name for f in dataclasses.fields(ExecutionPlan)}
        assert field_names == {"skill_id", "task_component", "inputs", "source_task"}


class TestInputFieldShape:
    def test_constructs_with_required_and_optional_fields(self) -> None:
        field_ = InputField(name="path", required=True, description="folder path")
        assert field_.name == "path"
        assert field_.required is True
        assert field_.description == "folder path"
        assert field_.default is None

    def test_default_value_is_carried_verbatim(self) -> None:
        field_ = InputField(
            name="model_name", required=False, description="model label", default="unnamed"
        )
        assert field_.default == "unnamed"

    def test_is_frozen(self) -> None:
        field_ = InputField(name="path", required=True, description="folder path")
        with pytest.raises(dataclasses.FrozenInstanceError):
            field_.required = False  # type: ignore[misc]


class TestExecutionBindingInputSchema:
    def test_defaults_to_an_empty_tuple(self) -> None:
        binding = ExecutionBinding(
            skill_id="fixture-skill",
            binding_id="fixture-skill-v1",
            runtime_id="fixture-runtime",
            approval_policy="allowed",
            verified=True,
        )
        assert binding.input_schema == ()

    def test_can_be_populated_explicitly(self) -> None:
        schema = (
            InputField(name="path", required=True, description="folder path"),
            InputField(name="model_name", required=False, description="model label"),
        )
        binding = ExecutionBinding(
            skill_id="fixture-skill",
            binding_id="fixture-skill-v1",
            runtime_id="fixture-runtime",
            approval_policy="allowed",
            verified=True,
            input_schema=schema,
        )
        assert binding.input_schema == schema

    def test_existing_trt_perf_analysis_binding_is_unaffected(self) -> None:
        """ADR-0009 §11: the one real ExecutionBinding construction site in
        this codebase must keep working, unchanged, with input_schema
        defaulting to empty — this ADR does not (yet) populate it."""
        binding = build_binding()
        assert binding.input_schema == ()
        assert binding.skill_id == "trt-perf-analysis"
        assert binding.verified is True
