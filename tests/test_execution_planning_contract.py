"""
Tests for the ADR-0010 execution-planning contract: ExecutionPlan,
ExecutionBinding.input_schema/InputField, and plan_execution()'s
deterministic V1 selection/input-completeness rule.

TestExecutionPlanShape/TestInputFieldShape/TestExecutionBindingInputSchema
prove the contract types are real, constructible Python with exactly the
documented shape, and that the existing ExecutionBinding construction site
(trt_perf_analysis.build_binding()) is unaffected by the new field.

TestPlanExecution covers the actual planning behavior (ADR-0010 §3): still
not wired into any LangGraph node — plan_execution() is a plain function,
exercised directly here, never through cv_agent.graph.workflow or CVAgent.
"""

from __future__ import annotations

import dataclasses

import pytest

from cv_agent.execution.binding import (
    ExecutionBinding,
    ExecutionBindingRegistry,
    InputField,
    RequiredFieldGroup,
)
from cv_agent.execution.runtimes.trt_perf_analysis import build_binding
from cv_agent.graph.planning import ExecutionPlan, plan_execution
from cv_agent.requirements.models import RequirementsAnalysis, SkillLink


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

    def test_existing_trt_perf_analysis_binding_declares_its_real_contract(self) -> None:
        """ADR-0009 §12 (Q20): build_binding() now populates its real
        path/data/model_name input_schema plus the path/data exactly_one
        group — see tests/test_execution_trt_perf_analysis.py for the full
        shape assertions; this just confirms the one real construction site
        still constructs and is still verified."""
        binding = build_binding()
        assert {f.name for f in binding.input_schema} == {"path", "data", "model_name"}
        assert len(binding.input_field_groups) == 1
        assert binding.input_field_groups[0].field_names == ("path", "data")
        assert binding.skill_id == "trt-perf-analysis"
        assert binding.verified is True


def _skill_link(
    skill_id: str, *, task_component: str = "person_detection", executable: bool = True
) -> SkillLink:
    return SkillLink(
        task_component=task_component,
        skill_id=skill_id,
        declared=False,
        matched_terms=("x",),
        executable=executable,
    )


def _analysis(
    skill_links: tuple[SkillLink, ...], *, original_request: str = "Detect people."
) -> RequirementsAnalysis:
    """Minimal RequirementsAnalysis — only skill_links/original_request
    matter to plan_execution(); every other required field is filled with
    an empty/neutral value."""
    return RequirementsAnalysis(
        original_request=original_request,
        problem_statement=f"The user requests: {original_request}",
        fields=(),
        candidate_tasks=(),
        capability_links=(),
        skill_links=skill_links,
        clarification_questions=(),
        assumptions=(),
        constraints=(),
        risks=(),
    )


def _binding(
    skill_id: str,
    *,
    input_schema: tuple[InputField, ...] = (),
    input_field_groups: tuple[RequiredFieldGroup, ...] = (),
) -> ExecutionBinding:
    return ExecutionBinding(
        skill_id=skill_id,
        binding_id=f"{skill_id}-fake-v1",
        runtime_id="fake-runtime",
        approval_policy="allowed",
        verified=True,
        input_schema=input_schema,
        input_field_groups=input_field_groups,
    )


def _registry(*bindings: ExecutionBinding) -> ExecutionBindingRegistry:
    registry = ExecutionBindingRegistry()
    for b in bindings:
        registry.register_binding(b)
    return registry


class TestPlanExecution:
    """ADR-0010 §3's deterministic V1 rule — plan_execution() exercised
    directly, no LangGraph, no CVAgent, no SkillExecutor."""

    # ── Selection: 0 / 1 / >1 candidates ────────────────────────────────

    def test_no_skill_links_means_no_executable_candidate(self) -> None:
        result = plan_execution(_analysis(()), _registry())
        assert result.status == "no_executable_candidate"
        assert result.plan is None

    def test_non_executable_skill_links_are_ignored(self) -> None:
        links = (_skill_link("skill-a", executable=False),)
        result = plan_execution(_analysis(links), _registry(_binding("skill-a")))
        assert result.status == "no_executable_candidate"

    def test_executable_but_no_registered_binding_is_not_a_candidate(self) -> None:
        """A SkillLink claiming executable=True against a registry that
        doesn't actually have a binding for it is not trusted blindly."""
        links = (_skill_link("skill-a", executable=True),)
        result = plan_execution(_analysis(links), _registry())  # empty registry
        assert result.status == "no_executable_candidate"

    def test_exactly_one_executable_candidate_creates_a_plan(self) -> None:
        links = (_skill_link("skill-a", task_component="person_detection"),)
        result = plan_execution(_analysis(links), _registry(_binding("skill-a")))
        assert result.status == "planned"
        assert result.plan == ExecutionPlan(
            skill_id="skill-a",
            task_component="person_detection",
            inputs={},
            source_task="Detect people.",
        )

    def test_two_different_executable_skills_are_ambiguous(self) -> None:
        links = (
            _skill_link("skill-a", task_component="person_detection"),
            _skill_link("skill-b", task_component="person_detection"),
        )
        result = plan_execution(
            _analysis(links), _registry(_binding("skill-a"), _binding("skill-b"))
        )
        assert result.status == "ambiguous_candidates"
        assert result.plan is None
        assert result.candidate_skill_ids == ("skill-a", "skill-b")

    def test_ambiguous_candidates_are_never_silently_narrowed_to_one(self) -> None:
        """Regression guard: whatever ordering/heuristic a future reader
        might be tempted to add, >1 distinct executable skill_id must never
        resolve to status == "planned"."""
        links = tuple(_skill_link(f"skill-{i}") for i in range(5))
        result = plan_execution(
            _analysis(links), _registry(*(_binding(f"skill-{i}") for i in range(5)))
        )
        assert result.status == "ambiguous_candidates"
        assert result.plan is None
        assert len(result.candidate_skill_ids) == 5

    def test_same_skill_matched_under_two_task_components_is_one_candidate(self) -> None:
        """skill_links can legitimately list the same skill_id twice under
        different task_components (an existing property of RequirementsAnalyzer,
        unrelated to planning) — that must count as ONE candidate, not two."""
        links = (
            _skill_link("skill-a", task_component="person_detection"),
            _skill_link("skill-a", task_component="action_recognition"),
        )
        result = plan_execution(_analysis(links), _registry(_binding("skill-a")))
        assert result.status == "planned"
        assert result.plan is not None
        assert result.plan.skill_id == "skill-a"

    def test_task_component_provenance_is_the_first_occurrence(self) -> None:
        links = (
            _skill_link("skill-a", task_component="person_detection"),
            _skill_link("skill-a", task_component="action_recognition"),
        )
        result = plan_execution(_analysis(links), _registry(_binding("skill-a")))
        assert result.plan is not None
        assert result.plan.task_component == "person_detection"

    # ── Input completeness ──────────────────────────────────────────────

    def test_missing_required_input_produces_no_plan(self) -> None:
        schema = (InputField(name="path", required=True, description="folder path"),)
        links = (_skill_link("skill-a"),)
        result = plan_execution(_analysis(links), _registry(_binding("skill-a", input_schema=schema)))
        assert result.status == "missing_required_inputs"
        assert result.plan is None
        assert result.missing_inputs == ("path",)

    def test_present_required_input_allows_a_plan(self) -> None:
        schema = (InputField(name="path", required=True, description="folder path"),)
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links),
            _registry(_binding("skill-a", input_schema=schema)),
            available_inputs={"path": "/tmp/some-folder"},
        )
        assert result.status == "planned"
        assert result.plan is not None
        assert result.plan.inputs == {"path": "/tmp/some-folder"}

    def test_optional_missing_input_does_not_block_a_plan(self) -> None:
        schema = (
            InputField(name="path", required=True, description="folder path"),
            InputField(name="model_name", required=False, description="model label"),
        )
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links),
            _registry(_binding("skill-a", input_schema=schema)),
            available_inputs={"path": "/tmp/some-folder"},
        )
        assert result.status == "planned"
        assert result.plan is not None
        assert "model_name" not in result.plan.inputs

    def test_no_input_fabrication_optional_default_is_never_applied(self) -> None:
        """InputField.default is deliberately never used to fill a value the
        caller did not explicitly supply — see plan_execution()'s docstring."""
        schema = (
            InputField(
                name="model_name", required=False, description="model label", default="unnamed"
            ),
        )
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links), _registry(_binding("skill-a", input_schema=schema))
        )
        assert result.status == "planned"
        assert result.plan is not None
        assert result.plan.inputs == {}

    def test_available_inputs_not_declared_in_schema_still_pass_through(self) -> None:
        """An empty/undeclared input_schema (true of trt-perf-analysis today,
        ADR-0009 §11) must not cause explicitly-supplied values to be
        silently dropped."""
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links),
            _registry(_binding("skill-a")),  # input_schema=() default
            available_inputs={"path": "/tmp/some-folder"},
        )
        assert result.status == "planned"
        assert result.plan is not None
        assert result.plan.inputs == {"path": "/tmp/some-folder"}

    def test_missing_inputs_listed_sorted_and_complete(self) -> None:
        schema = (
            InputField(name="path", required=True, description="folder path"),
            InputField(name="model_name", required=True, description="model label"),
        )
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links), _registry(_binding("skill-a", input_schema=schema))
        )
        assert result.status == "missing_required_inputs"
        assert result.missing_inputs == ("model_name", "path")

    # ── Field groups (ADR-0009 §12 / ADR-0010 §14, Q20) ─────────────────

    def _xor_schema_and_group(self) -> tuple[tuple[InputField, ...], tuple[RequiredFieldGroup, ...]]:
        schema = (
            InputField(name="path", required=False, description="folder path"),
            InputField(name="data", required=False, description="data list"),
        )
        groups = (RequiredFieldGroup(kind="exactly_one", field_names=("path", "data")),)
        return schema, groups

    def test_group_satisfied_by_either_member_alone(self) -> None:
        schema, groups = self._xor_schema_and_group()
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links),
            _registry(_binding("skill-a", input_schema=schema, input_field_groups=groups)),
            available_inputs={"data": [["layers.json"]]},
        )
        assert result.status == "planned"
        assert result.plan is not None
        assert result.plan.inputs == {"data": [["layers.json"]]}

    def test_group_unsatisfied_reports_every_member_name_missing(self) -> None:
        schema, groups = self._xor_schema_and_group()
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links),
            _registry(_binding("skill-a", input_schema=schema, input_field_groups=groups)),
        )
        assert result.status == "missing_required_inputs"
        assert result.missing_inputs == ("data", "path")

    def test_supplying_both_group_members_together_is_conflicting_inputs(self) -> None:
        """ADR-0010 §15 (review correction on PR #40): the Q20 decision was
        a true oneOf/XOR construct — "both given" is a genuine violation
        plan_execution() itself now catches and reports, before any plan,
        approval, or execution is ever attempted. plan_execution() still
        checks presence/count only, never value content — rejecting a
        structurally-invalid *value* for either field stays the runtime's
        job (e.g. TrtPerfAnalysisRuntime._build_argv())."""
        schema, groups = self._xor_schema_and_group()
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links),
            _registry(_binding("skill-a", input_schema=schema, input_field_groups=groups)),
            available_inputs={"path": "/tmp/x", "data": [["layers.json"]]},
        )
        assert result.status == "conflicting_inputs"
        assert result.plan is None
        assert result.conflicting_inputs == ("data", "path")
        assert result.missing_inputs == ()
        assert result.selected_skill_id == "skill-a"

    def test_conflict_takes_priority_over_a_separate_missing_required_field(self) -> None:
        """A conflict on one group and a genuinely missing, unrelated
        required field on the same candidate: the conflict is reported
        (status == "conflicting_inputs"), not silently dropped in favor of
        "missing_required_inputs" — a contradictory answer needs
        correcting regardless of what else is still missing."""
        schema, groups = self._xor_schema_and_group()
        schema = schema + (
            InputField(name="model_name", required=True, description="model label"),
        )
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links),
            _registry(_binding("skill-a", input_schema=schema, input_field_groups=groups)),
            available_inputs={"path": "/tmp/x", "data": [["layers.json"]]},
        )
        assert result.status == "conflicting_inputs"
        assert result.conflicting_inputs == ("data", "path")

    def test_group_and_individually_required_field_both_enforced(self) -> None:
        schema = (
            InputField(name="path", required=False, description="folder path"),
            InputField(name="data", required=False, description="data list"),
            InputField(name="model_name", required=True, description="model label"),
        )
        groups = (RequiredFieldGroup(kind="exactly_one", field_names=("path", "data")),)
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links),
            _registry(_binding("skill-a", input_schema=schema, input_field_groups=groups)),
            available_inputs={"path": "/tmp/x"},
        )
        assert result.status == "missing_required_inputs"
        assert result.missing_inputs == ("model_name",)

    # ── source_task mapping ──────────────────────────────────────────────

    def test_source_task_comes_from_original_request(self) -> None:
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links, original_request="Deploy RT-DETR on Jetson."),
            _registry(_binding("skill-a")),
        )
        assert result.plan is not None
        assert result.plan.source_task == "Deploy RT-DETR on Jetson."

    # ── Compatibility with the real binding shape ────────────────────────

    def test_plans_against_the_real_trt_perf_analysis_binding_shape(self) -> None:
        """build_binding()'s real path/data exactly_one group (ADR-0009 §12,
        Q20) is satisfied by supplying just one of them — the group check,
        not a planner bug, is what makes this "planned" rather than
        "missing_required_inputs"."""
        links = (_skill_link("trt-perf-analysis"),)
        result = plan_execution(
            _analysis(links),
            _registry(build_binding()),
            available_inputs={"path": "/tmp/perf-data"},
        )
        assert result.status == "planned"
        assert result.plan == ExecutionPlan(
            skill_id="trt-perf-analysis",
            task_component="person_detection",
            inputs={"path": "/tmp/perf-data"},
            source_task="Detect people.",
        )

    def test_neither_path_nor_data_reports_both_as_missing(self) -> None:
        """The real trt-perf-analysis binding with no path/data supplied:
        the unsatisfied exactly_one group reports both member names, not a
        composite string — matching plan_execution()'s documented shape."""
        links = (_skill_link("trt-perf-analysis"),)
        result = plan_execution(_analysis(links), _registry(build_binding()))
        assert result.status == "missing_required_inputs"
        assert result.missing_inputs == ("data", "path")

    # ── Result type itself ───────────────────────────────────────────────

    def test_planning_result_is_frozen(self) -> None:
        result = plan_execution(_analysis(()), _registry())
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.status = "planned"  # type: ignore[misc]


class TestPlanningResultSelectedIdentity:
    """ADR-0010 §13: selected_skill_id/selected_binding_id/
    selected_input_schema — the checkpointed identity+contract snapshot a
    same-session recovery round compares against on retry."""

    def test_populated_when_planned(self) -> None:
        schema = (InputField(name="path", required=True, description="folder path"),)
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links),
            _registry(_binding("skill-a", input_schema=schema)),
            available_inputs={"path": "/tmp/x"},
        )
        assert result.status == "planned"
        assert result.selected_skill_id == "skill-a"
        assert result.selected_binding_id == "skill-a-fake-v1"
        assert result.selected_input_schema == schema

    def test_populated_when_missing_required_inputs(self) -> None:
        schema = (InputField(name="path", required=True, description="folder path"),)
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links), _registry(_binding("skill-a", input_schema=schema))
        )
        assert result.status == "missing_required_inputs"
        assert result.selected_skill_id == "skill-a"
        assert result.selected_binding_id == "skill-a-fake-v1"
        assert result.selected_input_schema == schema

    def test_absent_when_no_executable_candidate(self) -> None:
        result = plan_execution(_analysis(()), _registry())
        assert result.status == "no_executable_candidate"
        assert result.selected_skill_id is None
        assert result.selected_binding_id is None
        assert result.selected_input_schema is None

    def test_absent_when_ambiguous(self) -> None:
        links = (_skill_link("skill-a"), _skill_link("skill-b"))
        result = plan_execution(
            _analysis(links), _registry(_binding("skill-a"), _binding("skill-b"))
        )
        assert result.status == "ambiguous_candidates"
        assert result.selected_skill_id is None
        assert result.selected_binding_id is None
        assert result.selected_input_schema is None

    def test_empty_input_schema_is_a_real_empty_tuple_not_none(self) -> None:
        """A binding with no declared input_schema at all (the default,
        true of trt-perf-analysis today) still reports a real, empty
        selected_input_schema — distinct from None, which means "no single
        candidate was selected" (the two prior tests)."""
        links = (_skill_link("skill-a"),)
        result = plan_execution(_analysis(links), _registry(_binding("skill-a")))
        assert result.status == "planned"
        assert result.selected_input_schema == ()
        assert result.selected_input_field_groups == ()

    def test_selected_input_field_groups_populated_when_planned(self) -> None:
        schema = (
            InputField(name="path", required=False, description="folder path"),
            InputField(name="data", required=False, description="data list"),
        )
        groups = (RequiredFieldGroup(kind="exactly_one", field_names=("path", "data")),)
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links),
            _registry(_binding("skill-a", input_schema=schema, input_field_groups=groups)),
            available_inputs={"path": "/tmp/x"},
        )
        assert result.status == "planned"
        assert result.selected_input_field_groups == groups

    def test_selected_input_field_groups_populated_when_missing_required_inputs(self) -> None:
        schema = (
            InputField(name="path", required=False, description="folder path"),
            InputField(name="data", required=False, description="data list"),
        )
        groups = (RequiredFieldGroup(kind="exactly_one", field_names=("path", "data")),)
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links),
            _registry(_binding("skill-a", input_schema=schema, input_field_groups=groups)),
        )
        assert result.status == "missing_required_inputs"
        assert result.selected_input_field_groups == groups

    def test_asdict_preserves_the_full_input_field_contract_per_entry(self) -> None:
        """Explicit verification (requested on PR #33 review): the
        `dataclasses.asdict()` serialization the workflow layer stores into
        AgentState (checkpointer-safe, per ADR-0003 §3) must preserve every
        InputField attribute — name, required, description, AND default —
        for every entry, in declaration order, not just field names. This
        is what `_node_plan_execution`'s identity+schema guard (ADR-0010
        §13.5) ultimately compares; if asdict() ever silently dropped a
        field, the guard's structural comparison would be comparing an
        incomplete contract without any test catching it here."""
        schema = (
            InputField(name="path", required=True, description="folder path"),
            InputField(
                name="model_name",
                required=False,
                description="model label",
                default="unnamed",
            ),
        )
        links = (_skill_link("skill-a"),)
        result = plan_execution(
            _analysis(links),
            _registry(_binding("skill-a", input_schema=schema)),
            available_inputs={"path": "/tmp/x"},
        )
        assert result.status == "planned"

        serialized = dataclasses.asdict(result)
        # dataclasses.asdict() applied directly (no LangGraph checkpoint
        # involved here) preserves the tuple container itself — only a real
        # checkpoint round-trip turns it into a list (ADR-0004's documented
        # instability; also true for candidate_skill_ids/missing_inputs
        # elsewhere in this same PlanningResult). The workflow-layer
        # comparison in _node_plan_execution normalizes both sides to
        # list[dict] before comparing regardless (ADR-0010 §13.5) — this
        # test verifies the per-entry field contents, not container type.
        assert serialized["selected_input_schema"] == (
            {"name": "path", "required": True, "description": "folder path", "default": None},
            {
                "name": "model_name",
                "required": False,
                "description": "model label",
                "default": "unnamed",
            },
        )
