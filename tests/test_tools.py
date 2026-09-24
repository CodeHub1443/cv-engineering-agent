"""
Tests for cv_agent.tools — ToolRegistry, ToolExecutor, ToolSpec, ToolInvoker.

Every test uses fake invokers/specs constructed in this file. No real
transport, MCP SDK, network, or API call is ever made. See ADR-0005
(Accepted) §7 for the acceptance criteria these tests satisfy.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_args

import pytest

from cv_agent.tools.executor import ToolExecutor
from cv_agent.tools.invoker import ToolInvoker
from cv_agent.tools.models import (
    ApprovalPolicy,
    ToolId,
    ToolInputField,
    ToolOutcome,
    ToolRequest,
    ToolRequiredFieldGroup,
    ToolResultStatus,
    ToolSpec,
)
from cv_agent.tools.registry import ToolRegistry, tool_pin_is_well_formed, tool_pin_mismatch


def _spec(
    tool_id: str = "fixture-tool",
    *,
    approval_policy: ApprovalPolicy = "allowed",
    verified: bool = True,
    input_schema: tuple[ToolInputField, ...] = (),
    input_field_groups: tuple[ToolRequiredFieldGroup, ...] = (),
) -> ToolSpec:
    return ToolSpec(
        tool_id=ToolId(tool_id),
        name=tool_id,
        description="A fake test tool.",
        transport="local",
        side_effecting=False,
        approval_policy=approval_policy,
        verified=verified,
        input_schema=input_schema,
        input_field_groups=input_field_groups,
    )


@dataclass
class FakeInvoker:
    """Configurable fake ToolInvoker — success, failure, or raise."""

    tool_id: str = "fixture-tool"
    outcome: ToolOutcome | None = None
    raises: Exception | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def invoke(self, spec: ToolSpec, request: ToolRequest) -> ToolOutcome:
        self.calls.append((spec.tool_id, dict(request.inputs)))
        if self.raises is not None:
            raise self.raises
        assert self.outcome is not None
        return self.outcome


def _registry_with(spec: ToolSpec, invoker: ToolInvoker | None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_spec(spec)
    if invoker is not None:
        registry.register_invoker(invoker)
    return registry


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


class TestToolSpecRegistration:
    def test_registering_a_spec_makes_it_listable(self) -> None:
        registry = ToolRegistry()
        spec = _spec()
        registry.register_spec(spec)

        assert registry.get_spec(ToolId("fixture-tool")) == spec
        assert registry.list_specs() == [spec]

    def test_duplicate_registration_of_same_tool_id_replaces_the_spec(self) -> None:
        registry = ToolRegistry()
        first = _spec(verified=False)
        second = _spec(verified=True, tool_id="fixture-tool")
        registry.register_spec(first)
        registry.register_spec(second)

        assert registry.get_spec(ToolId("fixture-tool")) == second
        assert registry.list_specs() == [second]

    def test_unregistered_tool_id_returns_none(self) -> None:
        registry = ToolRegistry()
        assert registry.get_spec(ToolId("nope")) is None
        assert registry.get_invoker(ToolId("nope")) is None


class TestInvokerRegistrationGeneration:
    """ADR-0005 §11 finding #1 — the mechanism that makes a replacement
    ToolInvoker during a paused workflow detectable."""

    def test_first_registration_is_generation_1(self) -> None:
        registry = ToolRegistry()
        invoker = FakeInvoker()
        registry.register_invoker(invoker)

        registration = registry.get_invoker_registration(ToolId("fixture-tool"))
        assert registration is not None
        assert registration == (invoker, 1)

    def test_reregistering_the_same_object_keeps_generation(self) -> None:
        registry = ToolRegistry()
        invoker = FakeInvoker()
        registry.register_invoker(invoker)
        registry.register_invoker(invoker)
        registry.register_invoker(invoker)

        registration = registry.get_invoker_registration(ToolId("fixture-tool"))
        assert registration is not None
        assert registration[1] == 1

    def test_registering_a_different_object_increments_generation(self) -> None:
        registry = ToolRegistry()
        first = FakeInvoker()
        second = FakeInvoker()
        registry.register_invoker(first)
        registry.register_invoker(second)

        registration = registry.get_invoker_registration(ToolId("fixture-tool"))
        assert registration is not None
        assert registration == (second, 2)

    def test_replacing_then_restoring_a_different_object_keeps_incrementing(self) -> None:
        """A -> B -> A is a real change each time, not a no-op — a naive
        'is this the same tool_id we saw before' check would wrongly treat
        the third registration as unchanged."""
        registry = ToolRegistry()
        a, b = FakeInvoker(), FakeInvoker()
        registry.register_invoker(a)
        registry.register_invoker(b)
        registry.register_invoker(a)

        registration = registry.get_invoker_registration(ToolId("fixture-tool"))
        assert registration is not None
        assert registration == (a, 3)

    def test_get_invoker_registration_returns_none_when_unregistered(self) -> None:
        registry = ToolRegistry()
        assert registry.get_invoker_registration(ToolId("fixture-tool")) is None


# --------------------------------------------------------------------------
# Tool pin: creation, well-formedness, mismatch
# --------------------------------------------------------------------------


class TestToolPinCreation:
    def test_pin_returns_none_when_no_spec_registered(self) -> None:
        registry = ToolRegistry()
        assert registry.pin(ToolId("fixture-tool")) is None

    def test_pin_combines_spec_pin_and_invoker_generation(self) -> None:
        registry = _registry_with(_spec(), FakeInvoker())
        pin = registry.pin(ToolId("fixture-tool"))

        assert pin is not None
        assert pin == {"spec": _spec().pin(), "invoker_generation": 1}

    def test_pin_invoker_generation_is_none_when_no_invoker_registered(self) -> None:
        registry = _registry_with(_spec(), invoker=None)
        pin = registry.pin(ToolId("fixture-tool"))

        assert pin is not None
        assert pin["invoker_generation"] is None


class TestToolPinWellFormedness:
    def test_a_real_pin_is_well_formed(self) -> None:
        registry = _registry_with(_spec(), FakeInvoker())
        pin = registry.pin(ToolId("fixture-tool"))

        assert tool_pin_is_well_formed(pin, tool_id=ToolId("fixture-tool"))

    def test_a_pin_for_a_different_tool_id_is_not_well_formed(self) -> None:
        registry = _registry_with(_spec(), FakeInvoker())
        pin = registry.pin(ToolId("fixture-tool"))

        assert not tool_pin_is_well_formed(pin, tool_id=ToolId("other-tool"))

    @pytest.mark.parametrize(
        "malformed",
        [
            None,
            {},
            "not-a-dict",
            {"spec": {}},  # missing invoker_generation
            {"spec": {}, "invoker_generation": 1, "extra": "key"},
            {"spec": {}, "invoker_generation": "one"},  # wrong type
            {"spec": {}, "invoker_generation": 0},  # < 1
            {"spec": {}, "invoker_generation": -1},
        ],
    )
    def test_malformed_shapes_are_rejected_and_never_raise(self, malformed: object) -> None:
        assert tool_pin_is_well_formed(malformed, tool_id=ToolId("fixture-tool")) is False

    def test_malformed_spec_pin_missing_a_key_is_rejected(self) -> None:
        registry = _registry_with(_spec(), FakeInvoker())
        pin = registry.pin(ToolId("fixture-tool"))
        assert pin is not None
        broken_spec = dict(pin["spec"])
        del broken_spec["verified"]
        broken_pin = {"spec": broken_spec, "invoker_generation": pin["invoker_generation"]}

        assert tool_pin_is_well_formed(broken_pin, tool_id=ToolId("fixture-tool")) is False


class TestToolPinMismatch:
    def test_identical_pins_are_equal(self) -> None:
        registry = _registry_with(_spec(), FakeInvoker())
        pin = registry.pin(ToolId("fixture-tool"))
        assert pin is not None

        assert tool_pin_mismatch(pin, pin) == ()

    def test_detects_a_changed_spec_field(self) -> None:
        registry = _registry_with(_spec(), FakeInvoker())
        pin = registry.pin(ToolId("fixture-tool"))
        assert pin is not None
        live = {"spec": dict(pin["spec"]), "invoker_generation": pin["invoker_generation"]}
        live["spec"]["verified"] = False

        codes = tool_pin_mismatch(pin, live)
        assert codes == ("spec.verified",)

    def test_detects_a_changed_invoker_generation(self) -> None:
        registry = _registry_with(_spec(), FakeInvoker())
        pin = registry.pin(ToolId("fixture-tool"))
        assert pin is not None
        live = {"spec": pin["spec"], "invoker_generation": 2}

        codes = tool_pin_mismatch(pin, live)
        assert codes == ("invoker_registration",)

    def test_malformed_expected_pin_reports_malformed_code(self) -> None:
        codes = tool_pin_mismatch("not-a-pin", {"spec": {}, "invoker_generation": None})
        assert codes == ("tool_pin_malformed",)


# --------------------------------------------------------------------------
# Fail-closed behavior
# --------------------------------------------------------------------------


class TestFailClosedBehavior:
    def test_unregistered_tool_is_not_executable(self) -> None:
        registry = ToolRegistry()
        executor = ToolExecutor(registry)

        result = executor.invoke(ToolId("never-registered"), ToolRequest())

        assert result.status == "not_executable"
        assert result.error is not None
        assert result.error.category == "no_tool"
        assert executor.can_invoke(ToolId("never-registered")) is False

    def test_unverified_spec_is_not_executable(self) -> None:
        registry = _registry_with(_spec(verified=False), FakeInvoker())
        executor = ToolExecutor(registry)

        result = executor.invoke(ToolId("fixture-tool"), ToolRequest())

        assert result.status == "not_executable"
        assert result.error is not None
        assert result.error.category == "tool_not_verified"
        assert executor.can_invoke(ToolId("fixture-tool")) is False

    def test_spec_with_no_registered_invoker_is_not_executable(self) -> None:
        registry = _registry_with(_spec(verified=True), invoker=None)
        executor = ToolExecutor(registry)

        result = executor.invoke(ToolId("fixture-tool"), ToolRequest())

        assert result.status == "not_executable"
        assert result.error is not None
        assert result.error.category == "no_tool"


# --------------------------------------------------------------------------
# Invocation and ToolOutcome -> ToolResult
# --------------------------------------------------------------------------


class TestInvocation:
    def test_verified_spec_with_invoker_is_invocable(self) -> None:
        registry = _registry_with(_spec(), FakeInvoker())
        executor = ToolExecutor(registry)

        assert executor.can_invoke(ToolId("fixture-tool")) is True

    def test_successful_invocation_reports_completed_with_output(self) -> None:
        invoker = FakeInvoker(outcome=ToolOutcome(success=True, output={"ok": 1}))
        registry = _registry_with(_spec(), invoker)
        executor = ToolExecutor(registry)

        result = executor.invoke(ToolId("fixture-tool"), ToolRequest(inputs={"x": 1}))

        assert result.status == "completed"
        assert result.ok is True
        assert result.output == {"ok": 1}
        assert invoker.calls == [("fixture-tool", {"x": 1})]

    def test_failed_invocation_reports_failed_with_error(self) -> None:
        invoker = FakeInvoker(outcome=ToolOutcome(success=False, error_message="boom"))
        registry = _registry_with(_spec(), invoker)
        executor = ToolExecutor(registry)

        result = executor.invoke(ToolId("fixture-tool"), ToolRequest())

        assert result.status == "failed"
        assert result.ok is False
        assert result.error is not None
        assert result.error.category == "transport_error"
        assert result.error.message == "boom"

    def test_invoker_exception_is_caught_and_reported_as_failed(self) -> None:
        invoker = FakeInvoker(raises=RuntimeError("kaboom"))
        registry = _registry_with(_spec(), invoker)
        executor = ToolExecutor(registry)

        result = executor.invoke(ToolId("fixture-tool"), ToolRequest())

        assert result.status == "failed"
        assert result.error is not None
        assert result.error.category == "transport_error"
        assert "kaboom" in result.error.message


class TestTrustBoundary:
    """ADR-0005 §11 finding #3 — a ToolInvoker cannot set tool_id, status,
    or evidence; only ToolExecutor constructs the final ToolResult."""

    def test_tool_outcome_has_no_envelope_fields(self) -> None:
        """Structural guarantee, not just a runtime check: ToolOutcome's own
        declared fields are exactly success/output/error_message — there is
        no tool_id/status/evidence field an invoker could even try to set."""
        outcome_fields = {f.name for f in dataclasses.fields(ToolOutcome)}
        assert outcome_fields == {"success", "output", "error_message"}

    def test_result_tool_id_and_status_come_from_the_executor_not_the_invoker(self) -> None:
        invoker = FakeInvoker(outcome=ToolOutcome(success=True, output={}))
        registry = _registry_with(_spec(), invoker)
        executor = ToolExecutor(registry)

        result = executor.invoke(ToolId("fixture-tool"), ToolRequest())

        # The requested tool_id and a status the executor itself derived
        # from outcome.success — never anything the fake invoker could have
        # smuggled in, since ToolOutcome has no field for either.
        assert result.tool_id == "fixture-tool"
        assert result.status == "completed"

    def test_evidence_invoker_generation_matches_registry_at_invocation_time(self) -> None:
        first = FakeInvoker(outcome=ToolOutcome(success=True))
        registry = _registry_with(_spec(), first)
        second = FakeInvoker(outcome=ToolOutcome(success=True))
        registry.register_invoker(second)  # generation now 2
        executor = ToolExecutor(registry)

        result = executor.invoke(ToolId("fixture-tool"), ToolRequest())

        assert result.evidence.invoker_generation == 2
        assert second.calls  # the current (generation-2) invoker ran
        assert first.calls == []


class TestToolEvidence:
    def test_completed_result_has_started_and_completed_timestamps(self) -> None:
        invoker = FakeInvoker(outcome=ToolOutcome(success=True))
        registry = _registry_with(_spec(), invoker)
        executor = ToolExecutor(registry)

        result = executor.invoke(ToolId("fixture-tool"), ToolRequest())

        assert result.evidence.started_at is not None
        assert result.evidence.completed_at is not None
        assert result.evidence.tool_id == "fixture-tool"

    def test_not_executable_result_has_no_timestamps(self) -> None:
        registry = ToolRegistry()
        executor = ToolExecutor(registry)

        result = executor.invoke(ToolId("never-registered"), ToolRequest())

        assert result.evidence.started_at is None
        assert result.evidence.completed_at is None

    def test_provenance_and_execution_metadata_default_to_empty_dicts(self) -> None:
        invoker = FakeInvoker(outcome=ToolOutcome(success=True))
        registry = _registry_with(_spec(), invoker)
        executor = ToolExecutor(registry)

        result = executor.invoke(ToolId("fixture-tool"), ToolRequest())

        assert result.evidence.provenance == {}
        assert result.evidence.execution_metadata == {}


class TestToolResultStatusStarted:
    def test_started_is_a_declared_status_value(self) -> None:
        assert "started" in get_args(ToolResultStatus)

    def test_started_is_not_produced_by_any_synchronous_executor_path(self) -> None:
        """Mirrors ADR-0009 §3's identical documentation for
        SkillExecutionStatus — 'started' is reserved for a future
        asynchronous ToolInvoker; every outcome in this synchronous suite is
        terminal."""
        invoker = FakeInvoker(outcome=ToolOutcome(success=True))
        registry = _registry_with(_spec(), invoker)
        executor = ToolExecutor(registry)

        result = executor.invoke(ToolId("fixture-tool"), ToolRequest())

        assert result.status != "started"


# --------------------------------------------------------------------------
# Approval policy
# --------------------------------------------------------------------------


class TestApprovalPolicyBranching:
    def test_rejected_policy_is_always_rejected(self) -> None:
        invoker = FakeInvoker(outcome=ToolOutcome(success=True))
        registry = _registry_with(_spec(approval_policy="rejected"), invoker)
        executor = ToolExecutor(registry)

        result = executor.invoke(ToolId("fixture-tool"), ToolRequest(approved=True))

        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.category == "approval_denied"
        assert invoker.calls == []

    def test_approval_required_without_pin_is_rejected_regardless_of_approved(self) -> None:
        """Rule E1 (ADR-0003 §10, restated ADR-0005 §9 rule 2): an absent
        pin can never authorize an approval-required invocation."""
        invoker = FakeInvoker(outcome=ToolOutcome(success=True))
        registry = _registry_with(_spec(approval_policy="approval_required"), invoker)
        executor = ToolExecutor(registry)

        result = executor.invoke(
            ToolId("fixture-tool"), ToolRequest(approved=True, expected_tool_pin=None)
        )

        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.category == "approval_denied"
        assert invoker.calls == []

    def test_approval_required_without_approval_is_rejected(self) -> None:
        invoker = FakeInvoker(outcome=ToolOutcome(success=True))
        registry = _registry_with(_spec(approval_policy="approval_required"), invoker)
        executor = ToolExecutor(registry)
        pin = registry.pin(ToolId("fixture-tool"))

        result = executor.invoke(
            ToolId("fixture-tool"), ToolRequest(approved=False, expected_tool_pin=pin)
        )

        assert result.status == "rejected"
        assert invoker.calls == []

    def test_approval_required_with_pin_and_approval_invokes(self) -> None:
        invoker = FakeInvoker(outcome=ToolOutcome(success=True, output={}))
        registry = _registry_with(_spec(approval_policy="approval_required"), invoker)
        executor = ToolExecutor(registry)
        pin = registry.pin(ToolId("fixture-tool"))

        result = executor.invoke(
            ToolId("fixture-tool"), ToolRequest(approved=True, expected_tool_pin=pin)
        )

        assert result.status == "completed"
        assert len(invoker.calls) == 1

    def test_allowed_policy_invokes_without_approval_or_pin(self) -> None:
        invoker = FakeInvoker(outcome=ToolOutcome(success=True, output={}))
        registry = _registry_with(_spec(approval_policy="allowed"), invoker)
        executor = ToolExecutor(registry)

        result = executor.invoke(ToolId("fixture-tool"), ToolRequest(approved=False))

        assert result.status == "completed"


class TestGenerationAndPinMismatchFailClosed:
    """ADR-0005 §11 findings #1/#2 — the review's headline safety finding:
    a replaced ToolInvoker under a stale pin must never run."""

    def test_replaced_invoker_with_stale_pin_is_tool_mismatch_and_never_invoked(self) -> None:
        original = FakeInvoker(outcome=ToolOutcome(success=True))
        registry = _registry_with(_spec(approval_policy="approval_required"), original)
        stale_pin = registry.pin(ToolId("fixture-tool"))
        assert stale_pin is not None

        replacement = FakeInvoker(outcome=ToolOutcome(success=True))
        registry.register_invoker(replacement)  # generation now 2

        executor = ToolExecutor(registry)
        result = executor.invoke(
            ToolId("fixture-tool"),
            ToolRequest(approved=True, expected_tool_pin=stale_pin),
        )

        assert result.status == "not_executable"
        assert result.error is not None
        assert result.error.category == "tool_mismatch"
        assert original.calls == []
        assert replacement.calls == []

    def test_reregistering_the_same_invoker_object_leaves_a_captured_pin_valid(self) -> None:
        invoker = FakeInvoker(outcome=ToolOutcome(success=True, output={}))
        registry = _registry_with(_spec(approval_policy="approval_required"), invoker)
        pin = registry.pin(ToolId("fixture-tool"))

        registry.register_invoker(invoker)  # same object — generation unchanged

        executor = ToolExecutor(registry)
        result = executor.invoke(
            ToolId("fixture-tool"), ToolRequest(approved=True, expected_tool_pin=pin)
        )

        assert result.status == "completed"

    def test_pin_mismatch_is_detected_even_for_an_allowed_policy_tool(self) -> None:
        """ADR-0005 §9 rule 6: pin checking applies for ANY approval_policy
        whenever a pin is supplied, not only approval_required."""
        original = FakeInvoker(outcome=ToolOutcome(success=True))
        registry = _registry_with(_spec(approval_policy="allowed"), original)
        stale_pin = registry.pin(ToolId("fixture-tool"))
        assert stale_pin is not None

        replacement = FakeInvoker(outcome=ToolOutcome(success=True))
        registry.register_invoker(replacement)

        executor = ToolExecutor(registry)
        result = executor.invoke(
            ToolId("fixture-tool"), ToolRequest(expected_tool_pin=stale_pin)
        )

        assert result.status == "not_executable"
        assert result.error is not None
        assert result.error.category == "tool_mismatch"
        assert original.calls == []
        assert replacement.calls == []

    def test_malformed_pin_is_rejected_before_any_invocation(self) -> None:
        invoker = FakeInvoker(outcome=ToolOutcome(success=True))
        registry = _registry_with(_spec(approval_policy="approval_required"), invoker)
        executor = ToolExecutor(registry)

        result = executor.invoke(
            ToolId("fixture-tool"),
            ToolRequest(approved=True, expected_tool_pin={"not": "a real pin"}),
        )

        assert result.status == "not_executable"
        assert result.error is not None
        assert result.error.category == "tool_mismatch"
        assert invoker.calls == []


# --------------------------------------------------------------------------
# ToolRequiredFieldGroup
# --------------------------------------------------------------------------


class TestToolRequiredFieldGroupShape:
    def test_constructs_with_two_field_names(self) -> None:
        group = ToolRequiredFieldGroup(kind="exactly_one", field_names=("path", "data"))
        assert group.kind == "exactly_one"
        assert group.field_names == ("path", "data")
        assert group.description == ""

    def test_is_frozen(self) -> None:
        group = ToolRequiredFieldGroup(kind="exactly_one", field_names=("path", "data"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            group.field_names = ("a", "b")  # type: ignore[misc]

    def test_fewer_than_two_field_names_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least two names"):
            ToolRequiredFieldGroup(kind="exactly_one", field_names=("path",))

    def test_duplicate_field_names_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            ToolRequiredFieldGroup(kind="exactly_one", field_names=("path", "path"))


class TestToolSpecFieldGroupValidation:
    def _schema(self) -> tuple[ToolInputField, ...]:
        return (
            ToolInputField(name="path", required=False, description="folder path"),
            ToolInputField(name="data", required=False, description="data list"),
        )

    def test_valid_group_over_declared_optional_fields_constructs_cleanly(self) -> None:
        spec = _spec(
            input_schema=self._schema(),
            input_field_groups=(
                ToolRequiredFieldGroup(kind="exactly_one", field_names=("path", "data")),
            ),
        )
        assert len(spec.input_field_groups) == 1

    def test_group_referencing_an_undeclared_field_name_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="undeclared"):
            _spec(
                input_schema=self._schema(),
                input_field_groups=(
                    ToolRequiredFieldGroup(
                        kind="exactly_one", field_names=("path", "nonexistent")
                    ),
                ),
            )

    def test_group_member_marked_individually_required_is_rejected(self) -> None:
        schema = (
            ToolInputField(name="path", required=True, description="folder path"),
            ToolInputField(name="data", required=False, description="data list"),
        )
        with pytest.raises(ValueError, match="contradictory"):
            _spec(
                input_schema=schema,
                input_field_groups=(
                    ToolRequiredFieldGroup(kind="exactly_one", field_names=("path", "data")),
                ),
            )

    def test_defaults_to_empty_tuple(self) -> None:
        assert _spec().input_field_groups == ()

    def test_field_belonging_to_two_groups_is_rejected(self) -> None:
        schema = (
            ToolInputField(name="a", required=False, description=""),
            ToolInputField(name="b", required=False, description=""),
            ToolInputField(name="c", required=False, description=""),
        )
        with pytest.raises(ValueError, match="more than one ToolRequiredFieldGroup"):
            _spec(
                input_schema=schema,
                input_field_groups=(
                    ToolRequiredFieldGroup(kind="exactly_one", field_names=("a", "b")),
                    ToolRequiredFieldGroup(kind="exactly_one", field_names=("b", "c")),
                ),
            )

    def test_two_disjoint_groups_are_still_accepted(self) -> None:
        schema = (
            ToolInputField(name="a", required=False, description=""),
            ToolInputField(name="b", required=False, description=""),
            ToolInputField(name="c", required=False, description=""),
            ToolInputField(name="d", required=False, description=""),
        )
        spec = _spec(
            input_schema=schema,
            input_field_groups=(
                ToolRequiredFieldGroup(kind="exactly_one", field_names=("a", "b")),
                ToolRequiredFieldGroup(kind="exactly_one", field_names=("c", "d")),
            ),
        )
        assert len(spec.input_field_groups) == 2


# --------------------------------------------------------------------------
# Registry listing
# --------------------------------------------------------------------------


class TestRegistryListing:
    def test_list_specs_is_sorted_by_tool_id(self) -> None:
        registry = ToolRegistry()
        for tool_id in ("zebra-tool", "alpha-tool", "mid-tool"):
            registry.register_spec(_spec(tool_id=tool_id))

        ordered = [s.tool_id for s in registry.list_specs()]
        assert ordered == ["alpha-tool", "mid-tool", "zebra-tool"]

    def test_list_invokers_is_sorted_by_tool_id(self) -> None:
        registry = ToolRegistry()
        for tool_id in ("zebra-tool", "alpha-tool", "mid-tool"):
            registry.register_invoker(FakeInvoker(tool_id=tool_id))

        ordered = [i.tool_id for i in registry.list_invokers()]
        assert ordered == ["alpha-tool", "mid-tool", "zebra-tool"]

    def test_fresh_registry_has_no_specs_or_invokers(self) -> None:
        registry = ToolRegistry()
        assert registry.list_specs() == []
        assert registry.list_invokers() == []


# --------------------------------------------------------------------------
# ApprovalPolicy drift guard (ADR-0005 §11 finding #12)
# --------------------------------------------------------------------------


class TestApprovalPolicyDriftGuard:
    def test_approval_policy_value_set_matches_execution_boundary(self) -> None:
        from cv_agent.execution.models import ApprovalPolicy as ExecutionApprovalPolicy

        assert set(get_args(ApprovalPolicy)) == set(get_args(ExecutionApprovalPolicy))


# --------------------------------------------------------------------------
# input_schema / input_field_groups are non-enforcing
# --------------------------------------------------------------------------


class TestNonEnforcingInputSchema:
    def test_request_missing_a_declared_required_field_still_reaches_the_invoker(self) -> None:
        """ADR-0005 §11 finding #11: ToolExecutor never validates
        request.inputs against input_schema — that stays the invoker's own
        job, exactly as ADR-0009 §11 states for InputField."""
        schema = (ToolInputField(name="path", required=True, description="required, unchecked"),)
        invoker = FakeInvoker(outcome=ToolOutcome(success=True, output={}))
        registry = _registry_with(_spec(input_schema=schema), invoker)
        executor = ToolExecutor(registry)

        result = executor.invoke(ToolId("fixture-tool"), ToolRequest(inputs={}))

        assert result.status == "completed"
        assert invoker.calls == [("fixture-tool", {})]

    def test_request_violating_a_field_group_still_reaches_the_invoker(self) -> None:
        schema = (
            ToolInputField(name="path", required=False, description=""),
            ToolInputField(name="data", required=False, description=""),
        )
        groups = (ToolRequiredFieldGroup(kind="exactly_one", field_names=("path", "data")),)
        invoker = FakeInvoker(outcome=ToolOutcome(success=True, output={}))
        registry = _registry_with(
            _spec(input_schema=schema, input_field_groups=groups), invoker
        )
        executor = ToolExecutor(registry)

        # Neither path nor data supplied — a true XOR violation — but
        # ToolExecutor does not check this; only a planning/orchestration
        # connector (not part of this boundary) would.
        result = executor.invoke(ToolId("fixture-tool"), ToolRequest(inputs={}))

        assert result.status == "completed"


# --------------------------------------------------------------------------
# No automatic discovery or execution
# --------------------------------------------------------------------------


class TestNoAutomaticDiscoveryOrExecution:
    def test_fresh_registry_is_empty(self) -> None:
        assert ToolRegistry().list_specs() == []
        assert ToolRegistry().list_invokers() == []

    def test_importing_the_package_registers_nothing(self) -> None:
        """Guards against a future regression where a module-level side
        effect registers a spec/invoker on import — mirrors ADR-0009 §3/§7's
        'constructed empty, nothing auto-registers' assertion. See also
        TestArchitectureBoundary.test_no_tool_or_invoker_is_registered_by_this_package_itself
        for the structural (source-scan) version of this same guarantee."""
        import cv_agent.tools  # noqa: F401 — import-time side effects are what's under test

        assert ToolRegistry().list_specs() == []
        assert ToolRegistry().list_invokers() == []


# --------------------------------------------------------------------------
# Architecture boundary
# --------------------------------------------------------------------------


class TestArchitectureBoundary:
    """ADR-0005 §2/§3: cv_agent.tools is a leaf package — it must import
    nothing from cv_agent.execution, cv_agent.skills, cv_agent.graph, or
    cv_agent.llm. Mirrors tests/test_llm_anthropic.py's anthropic-SDK
    confinement test and ADR-0004's sqlite3-confinement test."""

    _FORBIDDEN = ("cv_agent.execution", "cv_agent.skills", "cv_agent.graph", "cv_agent.llm")

    def test_cv_agent_tools_imports_nothing_from_forbidden_layers(self) -> None:
        """Checks actual import statements only — a docstring/comment that
        merely *mentions* a forbidden layer's name (e.g. this package's own
        module docstrings explaining the boundary) is not a dependency."""
        import cv_agent.tools

        package_root = Path(cv_agent.tools.__file__).parent
        offenders: list[str] = []
        for py_file in package_root.rglob("*.py"):
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if not (stripped.startswith("import ") or stripped.startswith("from ")):
                    continue
                for forbidden in self._FORBIDDEN:
                    if forbidden in stripped:
                        offenders.append(f"{py_file.name}:{lineno}: {stripped}")
        assert offenders == [], f"cv_agent.tools imports a forbidden layer: {offenders}"

    def test_no_mcp_sdk_is_imported_anywhere_in_cv_agent_tools(self) -> None:
        import cv_agent.tools

        package_root = Path(cv_agent.tools.__file__).parent
        offenders: list[str] = []
        for py_file in package_root.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            for needle in ("import mcp", "from mcp", "modelcontextprotocol", "fastmcp"):
                if needle in text.lower():
                    offenders.append(f"{py_file.name}: {needle}")
        assert offenders == [], f"cv_agent.tools references an MCP SDK: {offenders}"

    def test_no_tool_or_invoker_is_registered_by_this_package_itself(self) -> None:
        """Zero ToolSpec/ToolInvoker instances are registered at module
        import time anywhere in cv_agent.tools — the boundary only, per
        ADR-0005 §3. Checks for a *call* (`.register_spec(`/
        `.register_invoker(`, i.e. some object's method invoked), not the
        method *definitions* on ToolRegistry itself, which naturally
        contain the same substrings (`def register_spec(...)`)."""
        import cv_agent.tools

        package_root = Path(cv_agent.tools.__file__).parent
        offenders: list[str] = []
        for py_file in package_root.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            if ".register_spec(" in text or ".register_invoker(" in text:
                offenders.append(py_file.name)
        assert offenders == [], (
            f"cv_agent.tools itself calls register_spec/register_invoker: {offenders}"
        )
