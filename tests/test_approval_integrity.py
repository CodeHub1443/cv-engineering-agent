"""
Regression tests for issue #43 - approval integrity (ADR-0003 section 10,
ADR-0009 section 14, ADR-0010 section 17).

Test IDs T1-T23 refer to the acceptance table in ADR-0003 section 10.13.
Graph tests run against the real compiled graph and a real MemorySaver;
node-level tests call the node closures directly to reach states the graph
cannot produce (a missing/malformed pin, a decision recorded before a
tampered pin) - exactly the fail-closed guards those states exercise.
Every fake runtime records its calls, so "never invoked" is asserted, not
inferred.
"""

from __future__ import annotations

import copy
import dataclasses
from pathlib import Path
from typing import Any

import pytest

from cv_agent.__main__ import _authorize_and_execute
from cv_agent.config.settings import AgentConfig
from cv_agent.execution.binding import (
    ExecutionBinding,
    ExecutionBindingRegistry,
    InputField,
    RequiredFieldGroup,
    canonical_json,
    pin_is_well_formed,
    pin_mismatch,
)
from cv_agent.execution.executor import SkillExecutor
from cv_agent.execution.models import RuntimeOutcome, SkillExecutionRequest
from cv_agent.graph import workflow
from cv_agent.graph.workflow import (
    _make_approval_gate_node,
    _make_execute_node,
    _make_plan_execution_node,
)
from cv_agent.runtime.agent import CVAgent
from cv_agent.skills.inventory import SkillInventory
from cv_agent.skills.local import LocalSkillSource
from tests.test_execution import FakeRuntime as ExecFakeRuntime
from tests.test_execution import _skill as _exec_skill
from tests.test_workflow import (
    _PLANNING_TASK,
    FakeRuntime,
    TestChooseCandidateInterrupt as _CC,
    TestPlanExecutionIntegration as _T,
    _resume,
    _start,
    _write_planning_skill,
)

_SKILL = "trt-perf-analysis"
_OK = RuntimeOutcome(success=True, output={"ok": True})


# ── helpers ───────────────────────────────────────────────────────────────


def _paused(
    tmp_path: Path,
    *,
    sid: str = "ai-1",
    policy: str = "approval_required",
    **register_kwargs: Any,
):
    """Start a real workflow that pauses at the approval interrupt."""
    reg = ExecutionBindingRegistry()
    rt = _T._register(reg, _SKILL, approval_policy=policy, **register_kwargs)
    graph = _T()._graph_for(tmp_path, reg, skill_ids=(_SKILL,))
    started = _start(graph, _PLANNING_TASK, sid)
    assert started["__interrupt__"][0].value["type"] == "approval"
    return graph, reg, rt, sid, started


def _current(reg: ExecutionBindingRegistry, skill_id: str = _SKILL) -> ExecutionBinding:
    binding = reg.get_binding(skill_id)
    assert binding is not None
    return binding


def _spy_on_execute(agent: CVAgent) -> list[SkillExecutionRequest]:
    """Record every request `agent.execute` receives, then delegate."""
    seen: list[SkillExecutionRequest] = []
    real = agent.execute

    def spy(skill: Any, request: SkillExecutionRequest) -> Any:
        seen.append(request)
        return real(skill, request)

    agent.execute = spy  # type: ignore[method-assign]
    return seen


def _swap_binding(reg: ExecutionBindingRegistry, **changes: Any) -> ExecutionBinding:
    """Re-register the skill's binding with `changes`, same runtime otherwise."""
    replaced = dataclasses.replace(_current(reg, _SKILL), **changes)
    reg.register_binding(replaced)
    return replaced


def _replacement(
    reg: ExecutionBindingRegistry,
    *,
    policy: str,
    runtime_id: str = "replacement-rt",
    binding_id: str = f"{_SKILL}-REPLACEMENT",
) -> FakeRuntime:
    rt = FakeRuntime(runtime_id=runtime_id, outcome=RuntimeOutcome(success=True, output={}))
    reg.register_runtime(rt)
    reg.register_binding(
        ExecutionBinding(
            skill_id=_SKILL,
            binding_id=binding_id,
            runtime_id=runtime_id,
            approval_policy=policy,  # type: ignore[arg-type]
            verified=True,
        )
    )
    return rt


def _assert_failure(
    result: dict[str, Any], *, status: str, category: str, decision: str | None
) -> None:
    """T20 - the failure-path invariants of ADR-0003 section 10.10."""
    er = result["execution_result"]
    assert er["status"] == status
    assert er["error"]["category"] == category
    assert result["approval_decision"] == decision  # recorded decision preserved
    assert result["status"] == "done"  # terminal
    assert result["planning_result"]["plan"] is None  # plan cleared
    assert result["pending_execution"] is not None  # audit record kept
    nodes = [s["node"] for s in result["steps"]]
    assert nodes.count("plan_execution") == 1  # no silent re-plan
    assert nodes.count("approval_gate") == 1  # no re-ask
    assert nodes.count("execute") == 1


def _message(result: dict[str, Any]) -> str:
    return result["execution_result"]["error"]["message"]


def _node_env(tmp_path: Path, reg: ExecutionBindingRegistry):
    _write_planning_skill(tmp_path, _SKILL)
    executor = SkillExecutor(reg)
    inventory = SkillInventory(
        sources=(LocalSkillSource(roots=(tmp_path,)),), is_executable=executor.can_execute
    )
    return (
        _make_approval_gate_node(executor),
        _make_execute_node(executor, inventory),
        _make_plan_execution_node(reg),
    )


def _state(pending: dict[str, Any] | None, decision: str | None = None) -> dict[str, Any]:
    return {
        "pending_execution": pending,
        "approval_decision": decision,
        "steps": [],
        "planning_result": {"status": "planned", "plan": {"skill_id": _SKILL}},
    }


def _pending(pin: Any = ..., **extra: Any) -> dict[str, Any]:
    pending: dict[str, Any] = {"skill_id": _SKILL, "inputs": {}, "task": "t", **extra}
    if pin is not ...:
        pending["execution_pin"] = pin
    return pending


def _registered(policy: str = "approval_required", **binding_kwargs: Any):
    reg = ExecutionBindingRegistry()
    rt = FakeRuntime(runtime_id="rt-1", outcome=_OK)
    reg.register_runtime(rt)
    reg.register_binding(
        ExecutionBinding(
            skill_id=_SKILL,
            binding_id="b-1",
            runtime_id="rt-1",
            approval_policy=policy,  # type: ignore[arg-type]
            verified=True,
            **binding_kwargs,
        )
    )
    return reg, rt


class _ExplodingRegistry(ExecutionBindingRegistry):
    """Any registry read fails the test - proves a code path reads none."""

    def get_binding(self, skill_id: str):  # type: ignore[override]
        raise AssertionError("registry read: get_binding")

    def get_runtime(self, runtime_id: str):  # type: ignore[override]
        raise AssertionError("registry read: get_runtime")

    def get_runtime_registration(self, runtime_id: str):  # type: ignore[override]
        raise AssertionError("registry read: get_runtime_registration")

    def pin(self, skill_id: str):  # type: ignore[override]
        raise AssertionError("registry read: pin")


# ── T1-T4: the original reproductions (issue #43, scenarios A-D) ──────────


@pytest.mark.parametrize(
    "policy,decision,status,category,recorded",
    [
        pytest.param(
            "approval_required", "approved", "not_executable", "binding_mismatch", "approved",
            id="T1-A-replacement-approved",
        ),
        pytest.param(
            "approval_required", "rejected", "rejected", "approval_denied", "rejected",
            id="T2-B-replacement-rejected",
        ),
        pytest.param(
            "allowed", "rejected", "rejected", "approval_denied", "rejected",
            id="T3-C-allowed-replacement-rejected",
        ),
        pytest.param(
            "allowed", "approved", "not_executable", "binding_mismatch", "approved",
            id="T4-D-allowed-replacement-approved",
        ),
    ],
)
def test_original_reproductions(
    tmp_path: Path, policy: str, decision: str, status: str, category: str, recorded: str
) -> None:
    graph, reg, original_rt, sid, _ = _paused(tmp_path)
    replacement = _replacement(reg, policy=policy)

    result = _resume(graph, sid, decision)

    _assert_failure(result, status=status, category=category, decision=recorded)
    assert replacement.calls == []
    assert original_rt.calls == []


# ── T5: same-binding_id policy flips, both directions ─────────────────────


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_t5_same_binding_id_flip_to_allowed_after_pause(tmp_path: Path, decision: str) -> None:
    graph, reg, rt, sid, _ = _paused(tmp_path)
    _swap_binding(reg, approval_policy="allowed")  # same binding_id, same runtime

    result = _resume(graph, sid, decision)

    if decision == "rejected":  # a rejection always wins (Invariant R)
        _assert_failure(result, status="rejected", category="approval_denied", decision="rejected")
    else:
        _assert_failure(
            result, status="not_executable", category="binding_mismatch", decision="approved"
        )
        assert "binding.approval_policy" in _message(result)
    assert rt.calls == []


def test_t5_same_binding_id_flip_to_approval_required_executor_level() -> None:
    """allowed -> approval_required cannot happen inside a graph pause (an
    `allowed` pin has no pause after capture), so it is proven at the executor
    that the graph delegates to: a pin taken from an `allowed` binding does not
    survive the policy flipping to approval_required, even with approved=True."""
    reg, rt = _registered("allowed")
    pin = reg.pin(_SKILL)
    reg.register_binding(dataclasses.replace(_current(reg, _SKILL), approval_policy="approval_required"))

    result = SkillExecutor(reg).execute(
        _exec_skill(_SKILL), SkillExecutionRequest(approved=True, expected_binding_pin=pin)
    )

    assert result.status == "not_executable"
    assert result.error is not None and result.error.category == "binding_mismatch"
    assert "binding.approval_policy" in result.error.message
    assert rt.calls == []


# ── T6: binding / description / schema / groups / verified flips ──────────

_SCHEMA = (
    InputField(name="path", required=False, description="folder path"),
    InputField(name="data", required=False, description="data list"),
)
_XOR = (RequiredFieldGroup(kind="exactly_one", field_names=("path", "data")),)


@pytest.mark.parametrize(
    "changes,code",
    [
        pytest.param({"description": "reworded"}, "binding.description", id="description"),
        pytest.param({"verified": False}, "binding.verified", id="verified"),
        pytest.param({"binding_id": "other-id"}, "binding.binding_id", id="binding_id"),
        pytest.param(
            {"input_schema": (InputField(name="path", required=False, description="CHANGED"), _SCHEMA[1])},
            "binding.input_schema",
            id="schema",
        ),
        pytest.param({"input_field_groups": _XOR}, "binding.input_field_groups", id="groups"),
    ],
)
def test_t6_same_skill_binding_field_flips(tmp_path: Path, changes: dict[str, Any], code: str) -> None:
    graph, reg, rt, sid, _ = _paused(tmp_path, input_schema=_SCHEMA)
    _swap_binding(reg, **changes)

    result = _resume(graph, sid, "approved")

    _assert_failure(result, status="not_executable", category="binding_mismatch", decision="approved")
    assert code in _message(result)
    assert rt.calls == []


# ── T7: runtime replacement ───────────────────────────────────────────────


def test_t7a_different_runtime_id(tmp_path: Path) -> None:
    graph, reg, rt, sid, _ = _paused(tmp_path)
    other = FakeRuntime(runtime_id="other-rt", outcome=_OK)
    reg.register_runtime(other)
    _swap_binding(reg, runtime_id="other-rt")  # same binding_id

    result = _resume(graph, sid, "approved")

    _assert_failure(result, status="not_executable", category="binding_mismatch", decision="approved")
    assert "binding.runtime_id" in _message(result)
    assert rt.calls == [] and other.calls == []


def test_t7b_same_runtime_id_new_object(tmp_path: Path) -> None:
    graph, reg, rt, sid, _ = _paused(tmp_path)
    new = FakeRuntime(runtime_id=rt.runtime_id, outcome=_OK)
    reg.register_runtime(new)

    result = _resume(graph, sid, "approved")

    _assert_failure(result, status="not_executable", category="binding_mismatch", decision="approved")
    assert "runtime_registration" in _message(result)
    assert rt.calls == [] and new.calls == []


def test_t7c_a_to_b_to_a(tmp_path: Path) -> None:
    graph, reg, rt, sid, _ = _paused(tmp_path)
    reg.register_runtime(FakeRuntime(runtime_id=rt.runtime_id, outcome=_OK))  # B
    reg.register_runtime(rt)  # back to A: the original object, but generation 3

    result = _resume(graph, sid, "approved")

    _assert_failure(result, status="not_executable", category="binding_mismatch", decision="approved")
    assert "runtime_registration" in _message(result)
    assert rt.calls == []


def test_t7d_identical_reregistration_is_not_a_mismatch(tmp_path: Path) -> None:
    graph, reg, rt, sid, _ = _paused(tmp_path)
    reg.register_runtime(rt)  # same object again
    reg.register_binding(dataclasses.replace(_current(reg, _SKILL)))

    result = _resume(graph, sid, "approved")

    assert result["execution_result"]["status"] == "completed"
    assert result["approval_decision"] == "approved"
    assert len(rt.calls) == 1


# ── T8: runtime-generation states ─────────────────────────────────────────


def test_t8_registry_generation_semantics() -> None:
    reg = ExecutionBindingRegistry()
    a = FakeRuntime(runtime_id="rt", outcome=_OK)
    b = FakeRuntime(runtime_id="rt", outcome=_OK)
    assert reg.get_runtime_registration("rt") is None
    reg.register_runtime(a)
    assert reg.get_runtime_registration("rt") == (a, 1)
    reg.register_runtime(a)  # identical: unchanged
    assert reg.get_runtime_registration("rt") == (a, 1)
    reg.register_runtime(b)  # replacement
    assert reg.get_runtime_registration("rt")[1] == 2  # type: ignore[index]
    reg.register_runtime(a)  # A -> B -> A still bumps
    assert reg.get_runtime_registration("rt") == (a, 3)
    assert reg.get_runtime("rt") is a
    assert reg.list_runtimes() == [a]


def test_t8_pin_records_none_for_an_unregistered_runtime_and_none_without_a_binding() -> None:
    reg = ExecutionBindingRegistry()
    assert reg.pin(_SKILL) is None
    reg.register_binding(ExecutionBinding(_SKILL, "b", "late-rt", "allowed", True))
    assert reg.pin(_SKILL)["runtime_generation"] is None  # type: ignore[index]
    reg.register_runtime(FakeRuntime(runtime_id="late-rt", outcome=_OK))
    assert reg.pin(_SKILL)["runtime_generation"] == 1  # type: ignore[index]


def _caller_supplied_graph(tmp_path: Path, reg: ExecutionBindingRegistry):
    return _T()._graph_for(tmp_path, reg, skill_ids=(_SKILL,))


_CALLER_PLAN = {"skill_id": _SKILL, "inputs": {}, "task": "run it"}


def test_t8_runtime_registered_after_capture_is_a_mismatch(tmp_path: Path) -> None:
    reg = ExecutionBindingRegistry()
    reg.register_binding(ExecutionBinding(_SKILL, "b-1", "late-rt", "approval_required", True))
    graph = _caller_supplied_graph(tmp_path, reg)
    started = _start(graph, _PLANNING_TASK, "t8-a", pending_execution=dict(_CALLER_PLAN))
    assert started["__interrupt__"][0].value["type"] == "approval"
    assert started["pending_execution"]["execution_pin"]["runtime_generation"] is None
    late = FakeRuntime(runtime_id="late-rt", outcome=_OK)
    reg.register_runtime(late)  # appeared after capture: never approved

    result = _resume(graph, "t8-a", "approved")

    assert result["execution_result"]["error"]["category"] == "binding_mismatch"
    assert "runtime_registration" in _message(result)
    assert late.calls == []


def test_t8_runtime_still_unregistered_falls_through_to_no_binding(tmp_path: Path) -> None:
    reg = ExecutionBindingRegistry()
    reg.register_binding(ExecutionBinding(_SKILL, "b-1", "late-rt", "approval_required", True))
    graph = _caller_supplied_graph(tmp_path, reg)
    _start(graph, _PLANNING_TASK, "t8-b", pending_execution=dict(_CALLER_PLAN))

    result = _resume(graph, "t8-b", "approved")

    assert result["execution_result"]["status"] == "not_executable"
    assert result["execution_result"]["error"]["category"] == "no_binding"


# ── T9 / T10: missing and malformed pins (node level) ─────────────────────


def _assert_unusable_pin(tmp_path: Path, pending: dict[str, Any], code: str) -> None:
    reg, rt = _registered()
    gate, execute, _ = _node_env(tmp_path, reg)

    gate_update = gate(_state(pending))  # must not interrupt (would raise outside a graph)
    assert "approval_decision" not in gate_update  # stays None (D7), never not_required

    update = execute(_state(pending))
    er = update["execution_result"]
    assert er["status"] == "not_executable"
    assert er["error"]["category"] == "binding_mismatch"
    assert er["error"]["message"] == f"integrity check failed: {code}"
    assert rt.calls == []  # executor not reached
    assert "approval_decision" not in update
    assert update["planning_result"]["plan"] is None
    assert update["status"] == "done"


def test_t9_missing_pin_key(tmp_path: Path) -> None:
    _assert_unusable_pin(tmp_path, _pending(), "execution_pin_missing")


def _good_pin() -> dict[str, Any]:
    reg, _ = _registered()
    return reg.pin(_SKILL)  # type: ignore[return-value]


def _mut(fn) -> dict[str, Any]:
    pin = copy.deepcopy(_good_pin())
    fn(pin)
    return pin


_MALFORMED: dict[str, Any] = {
    "not-a-dict": "garbage",
    "empty-dict": {},
    "missing-key": _mut(lambda p: p.pop("runtime_generation")),
    "extra-key": _mut(lambda p: p.update(extra=1)),
    "binding-extra-key": _mut(lambda p: p["binding"].update(extra=1)),
    "binding-missing-key": _mut(lambda p: p["binding"].pop("description")),
    "wrong-type-verified": _mut(lambda p: p["binding"].update(verified="yes")),
    "wrong-type-description": _mut(lambda p: p["binding"].update(description=5)),
    "bad-policy-literal": _mut(lambda p: p["binding"].update(approval_policy="maybe")),
    "generation-true": _mut(lambda p: p.update(runtime_generation=True)),
    "generation-zero": _mut(lambda p: p.update(runtime_generation=0)),
    "generation-string": _mut(lambda p: p.update(runtime_generation="1")),
    "schema-entry-extra-key": _mut(
        lambda p: p["binding"].update(
            input_schema=[{"name": "a", "required": True, "description": "", "default": None, "x": 1}]
        )
    ),
    "group-field-names-not-list": _mut(
        lambda p: p["binding"].update(
            input_field_groups=[{"kind": "exactly_one", "field_names": "path", "description": ""}]
        )
    ),
    "skill-id-mismatch": _mut(lambda p: p["binding"].update(skill_id="some-other-skill")),
}


@pytest.mark.parametrize("pin", list(_MALFORMED.values()), ids=list(_MALFORMED))
def test_t10_malformed_pin(tmp_path: Path, pin: Any) -> None:
    assert not pin_is_well_formed(pin, skill_id=_SKILL)
    _assert_unusable_pin(tmp_path, _pending(pin), "execution_pin_malformed")


# ── T11: explicit None (no binding at capture) ────────────────────────────


def test_t11_explicit_none_pin_never_executes_even_if_a_binding_appears(tmp_path: Path) -> None:
    reg, rt = _registered("allowed")  # a binding + runtime exist NOW
    gate, execute, _ = _node_env(tmp_path, reg)
    pending = _pending(None)  # ... but none existed at capture

    assert gate(_state(pending))["approval_decision"] == "not_required"
    update = execute(_state(pending, "not_required"))

    er = update["execution_result"]
    assert er["status"] == "not_executable" and er["error"]["category"] == "no_binding"
    assert rt.calls == []  # executor not called
    assert update["planning_result"]["plan"] is None


def test_t11_end_to_end_caller_plan_without_a_binding(tmp_path: Path) -> None:
    reg = ExecutionBindingRegistry()
    graph = _caller_supplied_graph(tmp_path, reg)

    started = _start(graph, _PLANNING_TASK, "t11", pending_execution=dict(_CALLER_PLAN))

    assert "__interrupt__" not in started
    assert started["pending_execution"]["execution_pin"] is None
    assert started["approval_decision"] == "not_required"
    assert started["execution_result"]["error"]["category"] == "no_binding"
    assert started["status"] == "done"


# ── T12: caller-supplied plans are pinned at first observation ────────────


def test_t12_caller_plan_pinned_at_first_observation(tmp_path: Path) -> None:
    reg, rt = _registered()
    graph = _caller_supplied_graph(tmp_path, reg)
    started = _start(graph, _PLANNING_TASK, "t12", pending_execution=dict(_CALLER_PLAN))
    assert started["__interrupt__"][0].value["binding_id"] == "b-1"
    assert started["pending_execution"]["execution_pin"]["binding"]["binding_id"] == "b-1"
    _swap_binding_generic(reg, binding_id="b-2")  # mutation after first observation

    result = _resume(graph, "t12", "approved")

    assert result["execution_result"]["error"]["category"] == "binding_mismatch"
    assert "binding.binding_id" in _message(result)
    assert rt.calls == []


def _swap_binding_generic(reg: ExecutionBindingRegistry, **changes: Any) -> None:
    reg.register_binding(dataclasses.replace(_current(reg, _SKILL), **changes))


def test_t12_second_visit_never_repins(tmp_path: Path) -> None:
    reg, _ = _registered()
    _, _, plan_node = _node_env(tmp_path, reg)
    first = plan_node(_state({"skill_id": _SKILL, "inputs": {}, "task": "t"}))
    pinned = first["pending_execution"]
    assert pinned["execution_pin"]["binding"]["binding_id"] == "b-1"
    _swap_binding_generic(reg, binding_id="b-2")

    second = plan_node({**_state(pinned)})

    assert "pending_execution" not in second  # key present: left untouched


# ── T13: rejection precedence ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "pin",
    [
        pytest.param(..., id="missing-pin"),
        pytest.param("garbage", id="malformed-pin"),
        pytest.param(None, id="explicit-none-pin"),
        pytest.param(_mut(lambda p: p["binding"].update(binding_id="stale")), id="mismatching-pin"),
        pytest.param(_mut(lambda p: p.update(runtime_generation=99)), id="stale-runtime-generation"),
    ],
)
def test_t13_recorded_rejection_beats_every_pin_state_and_reads_no_registry(
    tmp_path: Path, pin: Any
) -> None:
    reg = _ExplodingRegistry()  # any registry read fails the test
    _write_planning_skill(tmp_path, _SKILL)
    executor = SkillExecutor(reg)
    inventory = SkillInventory(sources=(LocalSkillSource(roots=(tmp_path,)),))
    execute = _make_execute_node(executor, inventory)

    update = execute(_state(_pending(pin), "rejected"))

    er = update["execution_result"]
    assert er["status"] == "rejected" and er["error"]["category"] == "approval_denied"
    assert "approval_decision" not in update  # the recorded rejection is never rewritten
    assert update["planning_result"]["plan"] is None
    assert update["status"] == "done"


def test_t13_rejection_with_an_allowed_replacement_and_unregistered_runtime(tmp_path: Path) -> None:
    graph, reg, rt, sid, _ = _paused(tmp_path)
    reg.register_binding(ExecutionBinding(_SKILL, "brand-new", "no-such-runtime", "allowed", True))

    result = _resume(graph, sid, "rejected")

    _assert_failure(result, status="rejected", category="approval_denied", decision="rejected")
    assert rt.calls == []


# ── T14: decision inconsistent with the pinned policy (A1 guard) ──────────


@pytest.mark.parametrize(
    "policy,decision",
    [
        ("approval_required", "not_required"),
        ("approval_required", None),
        ("allowed", "approved"),
        ("allowed", None),
    ],
)
def test_t14_inconsistent_decision_is_never_executed(
    tmp_path: Path, policy: str, decision: str | None
) -> None:
    reg, rt = _registered(policy)
    _, execute, _ = _node_env(tmp_path, reg)

    update = execute(_state(_pending(reg.pin(_SKILL)), decision))

    er = update["execution_result"]
    assert er["status"] == "not_executable"
    assert er["error"]["message"] == "integrity check failed: approval_decision_inconsistent"
    assert rt.calls == []
    assert "approval_decision" not in update


def test_t14_consistent_allowed_decision_runs(tmp_path: Path) -> None:
    reg, rt = _registered("allowed")
    _, execute, _ = _node_env(tmp_path, reg)

    update = execute(_state(_pending(reg.pin(_SKILL)), "not_required"))

    assert update["execution_result"]["status"] == "completed"
    assert len(rt.calls) == 1
    assert "planning_result" not in update  # nothing cleared on success


# ── T15: gate replay safety ───────────────────────────────────────────────


def test_t15_gate_and_execute_read_no_registry_after_planning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, reg, rt, sid, _ = _paused(tmp_path)

    def boom(*a: Any, **k: Any) -> Any:
        raise AssertionError("registry read after planning")

    for name in ("get_binding", "get_runtime", "get_runtime_registration", "pin"):
        monkeypatch.setattr(reg, name, boom)

    # On resume LangGraph re-runs the gate's pre-interrupt code: it must read
    # only the checkpointed pin. A rejection then reaches execute, which must
    # not read the registry either.
    result = _resume(graph, sid, "rejected")

    _assert_failure(result, status="rejected", category="approval_denied", decision="rejected")
    assert rt.calls == []


# ── T16: no false positives ───────────────────────────────────────────────


def test_t16_unrelated_skill_binding_change_is_irrelevant(tmp_path: Path) -> None:
    graph, reg, rt, sid, _ = _paused(tmp_path)
    other = FakeRuntime(runtime_id="other-rt", outcome=_OK)
    reg.register_runtime(other)
    reg.register_binding(ExecutionBinding("some-other-skill", "o-1", "other-rt", "allowed", True))

    result = _resume(graph, sid, "approved")

    assert result["execution_result"]["status"] == "completed"
    assert len(rt.calls) == 1 and other.calls == []


# ── T17: direct executor callers ──────────────────────────────────────────


def _exec_registry(policy: str):
    rt = ExecFakeRuntime(runtime_id="fake-runtime", outcome=_OK)
    reg = ExecutionBindingRegistry()
    reg.register_runtime(rt)
    reg.register_binding(
        ExecutionBinding(_SKILL, "b1", "fake-runtime", policy, True)  # type: ignore[arg-type]
    )
    return reg, rt


def _run(reg: ExecutionBindingRegistry, **request: Any):
    return SkillExecutor(reg).execute(_exec_skill(_SKILL), SkillExecutionRequest(**request))


def test_t17_approval_required_without_a_pin_is_refused_even_when_approved() -> None:
    reg, rt = _exec_registry("approval_required")

    result = _run(reg, approved=True)

    assert result.status == "rejected"
    assert result.error is not None and result.error.category == "approval_denied"
    assert "not bound to an execution snapshot" in result.error.message
    assert rt.calls == []


def test_t17_allowed_without_a_pin_is_unchanged() -> None:
    reg, rt = _exec_registry("allowed")
    assert _run(reg).status == "completed" and len(rt.calls) == 1


@pytest.mark.parametrize("policy", ["allowed", "approval_required", "rejected"])
def test_t17_supplied_malformed_pin_fails_for_every_policy(policy: str) -> None:
    reg, rt = _exec_registry(policy)

    result = _run(reg, approved=True, expected_binding_pin={"nonsense": True})  # type: ignore[arg-type]

    assert result.status == "not_executable"
    assert result.error is not None and result.error.category == "binding_mismatch"
    assert result.error.message == "integrity check failed: execution_pin_malformed"
    assert rt.calls == []


def test_t17_supplied_pin_for_a_different_skill_is_malformed() -> None:
    reg, rt = _exec_registry("allowed")
    other_pin = copy.deepcopy(reg.pin(_SKILL))
    other_pin["binding"]["skill_id"] = "someone-else"  # type: ignore[index]

    result = _run(reg, expected_binding_pin=other_pin)

    assert result.error is not None and result.error.message.endswith("execution_pin_malformed")
    assert rt.calls == []


def test_t17_supplied_mismatch_never_invokes_and_matching_pin_completes() -> None:
    reg, rt = _exec_registry("approval_required")
    pin = reg.pin(_SKILL)
    reg.register_binding(dataclasses.replace(_current(reg, _SKILL), description="drift"))

    bad = _run(reg, approved=True, expected_binding_pin=pin)
    assert bad.status == "not_executable" and rt.calls == []
    assert bad.error is not None and bad.error.message == "integrity check failed: binding.description"

    good = _run(reg, approved=True, expected_binding_pin=reg.pin(_SKILL))
    assert good.status == "completed" and len(rt.calls) == 1


def test_t17_the_instance_invoked_is_the_instance_whose_generation_was_compared() -> None:
    class _Split(ExecutionBindingRegistry):
        decoy: Any = None

        def get_runtime(self, runtime_id: str):  # a separate lookup would return the decoy
            return self.decoy

    reg = _Split()
    real = ExecFakeRuntime(runtime_id="fake-runtime", outcome=_OK)
    reg.decoy = ExecFakeRuntime(runtime_id="fake-runtime", outcome=_OK)
    reg.register_runtime(real)
    reg.register_binding(ExecutionBinding(_SKILL, "b1", "fake-runtime", "allowed", True))

    result = _run(reg, expected_binding_pin=reg.pin(_SKILL))

    assert result.status == "completed"
    assert len(real.calls) == 1 and reg.decoy.calls == []


def test_t17_unpinnable_live_binding_is_a_mismatch_not_a_crash() -> None:
    reg, rt = _exec_registry("allowed")
    pin = reg.pin(_SKILL)
    reg.register_binding(
        ExecutionBinding(
            _SKILL, "b1", "fake-runtime", "allowed", True,
            input_schema=(InputField(name="x", required=False, description="", default=object()),),
        )
    )

    result = _run(reg, expected_binding_pin=pin)

    assert result.error is not None and "binding.unpinnable" in result.error.message
    assert rt.calls == []


# ── T18: direct CLI ───────────────────────────────────────────────────────


def _cli_agent(tmp_path: Path, policy: str):
    skill_dir = tmp_path / "fixture-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: fixture-skill\ndescription: fixture skill.\n---\nbody\n", encoding="utf-8"
    )
    agent = CVAgent(AgentConfig(skill_paths=(tmp_path,)))
    rt = ExecFakeRuntime(runtime_id="fake-runtime", outcome=_OK)
    agent.execution_bindings.register_runtime(rt)
    agent.execution_bindings.register_binding(
        ExecutionBinding("fixture-skill", "fx-1", "fake-runtime", policy, True)  # type: ignore[arg-type]
    )
    skill = agent.skills.get("fixture-skill")
    assert skill is not None
    return agent, skill, rt


def test_t18_registry_mutation_during_the_prompt_fails_closed(tmp_path: Path) -> None:
    agent, skill, rt = _cli_agent(tmp_path, "approval_required")
    binding = agent.execution_bindings.get_binding("fixture-skill")

    def prompt(_msg: str) -> str:  # the human is deciding ... and the registry changes
        agent.execution_bindings.register_binding(
            dataclasses.replace(binding, binding_id="swapped-during-prompt")
        )
        return "y"

    result = _authorize_and_execute(
        agent, skill, binding, inputs={}, task=None, approve_flag=False, prompt=prompt
    )

    assert result.status == "not_executable"
    assert result.error.category == "binding_mismatch"
    assert "binding.binding_id" in result.error.message
    assert rt.calls == []


def test_t18_pin_is_captured_before_the_prompt_and_passed_on_both_paths(tmp_path: Path) -> None:
    # --approve flag path
    (tmp_path / "p1").mkdir()
    agent, skill, rt = _cli_agent(tmp_path / "p1", "approval_required")
    binding = agent.execution_bindings.get_binding("fixture-skill")
    seen = _spy_on_execute(agent)

    def fail_if_prompted(_m: str) -> str:
        raise AssertionError("--approve must not prompt")

    ok = _authorize_and_execute(
        agent, skill, binding, inputs={}, task=None, approve_flag=True, prompt=fail_if_prompted
    )
    assert ok.status == "completed"
    assert seen[0].expected_binding_pin == agent.execution_bindings.pin("fixture-skill")

    # interactive "y" path
    result = _authorize_and_execute(
        agent, skill, binding, inputs={}, task=None, approve_flag=False, prompt=lambda m: "y"
    )
    assert result.status == "completed"
    assert seen[1].expected_binding_pin is not None


def test_t18_declined_prompt_runs_nothing_and_allowed_binding_passes_no_pin(tmp_path: Path) -> None:
    (tmp_path / "d").mkdir()
    agent, skill, rt = _cli_agent(tmp_path / "d", "approval_required")
    binding = agent.execution_bindings.get_binding("fixture-skill")
    assert (
        _authorize_and_execute(
            agent, skill, binding, inputs={}, task=None, approve_flag=False, prompt=lambda m: "n"
        )
        is None
    )
    assert rt.calls == []

    (tmp_path / "e").mkdir()
    agent2, skill2, rt2 = _cli_agent(tmp_path / "e", "allowed")
    binding2 = agent2.execution_bindings.get_binding("fixture-skill")
    seen = _spy_on_execute(agent2)
    result = _authorize_and_execute(
        agent2, skill2, binding2, inputs={}, task=None, approve_flag=False,
        prompt=lambda m: (_ for _ in ()).throw(AssertionError("allowed must not prompt")),
    )
    assert result.status == "completed" and seen[0].expected_binding_pin is None


# ── T19: canonical snapshot semantics ─────────────────────────────────────


def test_t19_pin_shape_is_exactly_the_documented_one() -> None:
    binding = ExecutionBinding(
        _SKILL, "b1", "rt", "approval_required", True, description="d",
        input_schema=(InputField("path", False, "p", default=("a", 1)),),
    )
    assert binding.pin() == {
        "skill_id": _SKILL, "binding_id": "b1", "runtime_id": "rt",
        "approval_policy": "approval_required", "verified": True, "description": "d",
        "input_schema": [{"name": "path", "required": False, "description": "p", "default": ["a", 1]}],
        "input_field_groups": [],
    }
    grouped = ExecutionBinding(
        _SKILL, "b1", "rt", "allowed", True, input_schema=_SCHEMA, input_field_groups=_XOR
    ).pin()
    assert grouped["input_field_groups"] == [
        {"kind": "exactly_one", "field_names": ["path", "data"], "description": ""}
    ]


def _pin_with(**binding_kwargs: Any) -> dict[str, Any]:
    reg = ExecutionBindingRegistry()
    reg.register_binding(ExecutionBinding(_SKILL, "b1", "rt", "allowed", True, **binding_kwargs))
    return reg.pin(_SKILL)  # type: ignore[return-value]


def test_t19_order_is_significant() -> None:
    a = _pin_with(input_schema=_SCHEMA)
    b = _pin_with(input_schema=tuple(reversed(_SCHEMA)))
    assert pin_mismatch(a, b) == ("binding.input_schema",)


def test_t19_equality_is_independent_of_container_type_and_key_order() -> None:
    assert canonical_json({"b": [1, 2], "a": {"y": 1, "x": 2}}) == canonical_json(
        {"a": {"x": 2, "y": 1}, "b": (1, 2)}
    )


@pytest.mark.parametrize("left,right", [(1, 1.0), (1, True), (0, False), (1.0, True)])
def test_t19_equality_is_type_sensitive(left: Any, right: Any) -> None:
    assert canonical_json(left) != canonical_json(right)
    a = _pin_with(input_schema=(InputField("x", False, "", default=left),))
    b = _pin_with(input_schema=(InputField("x", False, "", default=right),))
    assert pin_mismatch(a, b) == ("binding.input_schema",)


@pytest.mark.parametrize("bad", [object(), {1: "non-str key"}, float("nan"), float("inf"), {"a": {object()}}])
def test_t19_non_json_native_default_fails_at_the_pin_boundary_not_construction(bad: Any) -> None:
    binding = ExecutionBinding(  # construction is unaffected (A3: no constructor restriction)
        _SKILL, "b1", "rt", "allowed", True, input_schema=(InputField("x", False, "", default=bad),)
    )
    with pytest.raises(ValueError):
        binding.pin()
    reg = ExecutionBindingRegistry()
    reg.register_binding(binding)
    with pytest.raises(ValueError):
        reg.pin(_SKILL)


def test_t19_a_real_checkpoint_round_trip_produces_no_false_mismatch(tmp_path: Path) -> None:
    schema = (
        InputField("path", False, "folder", default=None),
        InputField("ratio", False, "a float", default=1.5),
        InputField("nested", False, "nested", default=[1, {"a": 2.5, "b": [True, None]}]),
    )
    graph, reg, rt, sid, started = _paused(tmp_path, input_schema=schema)
    checkpointed = graph.get_state({"configurable": {"thread_id": sid}}).values
    pin = checkpointed["pending_execution"]["execution_pin"]
    assert canonical_json(pin) == canonical_json(reg.pin(_SKILL))
    assert pin_mismatch(pin, reg.pin(_SKILL)) == ()

    result = _resume(graph, sid, "approved")

    assert result["execution_result"]["status"] == "completed"
    assert len(rt.calls) == 1


def test_t19_a_binding_that_cannot_be_pinned_fails_closed_end_to_end(tmp_path: Path) -> None:
    reg = ExecutionBindingRegistry()
    rt = FakeRuntime(runtime_id="rt-x", outcome=_OK)
    reg.register_runtime(rt)
    reg.register_binding(
        ExecutionBinding(
            _SKILL, "bx", "rt-x", "approval_required", True,
            # NaN survives the checkpoint serializer (an object() default would
            # already crash planning_result's own checkpointing, pre-#43) but is
            # not JSON-native, so it cannot be pinned.
            input_schema=(InputField("x", False, "", default=float("nan")),),
        )
    )
    graph = _T()._graph_for(tmp_path, reg, skill_ids=(_SKILL,))

    result = _start(graph, _PLANNING_TASK, "t19-unpinnable")

    assert "__interrupt__" not in result  # never shown to a human for approval
    assert result["approval_decision"] is None
    assert result["execution_result"]["error"]["message"] == (
        "integrity check failed: execution_pin_malformed"
    )
    assert rt.calls == []


# ── T21: description drift through input recovery ─────────────────────────

_PATH_REQUIRED = (InputField(name="path", required=True, description="folder path"),)


def _recovery_paused(tmp_path: Path, description: str = "orig description"):
    reg = ExecutionBindingRegistry()
    rt = _T._register(reg, _SKILL, input_schema=_PATH_REQUIRED, description=description)
    graph = _T()._graph_for(tmp_path, reg, skill_ids=(_SKILL,))
    started = _start(graph, _PLANNING_TASK, "t21")
    assert started["__interrupt__"][0].value["type"] == "provide_execution_inputs"
    return graph, reg, rt


def _assert_description_mismatch(result: dict[str, Any]) -> None:
    recovery = result["execution_input_recovery"]
    assert recovery["outcome"] == "binding_mismatch"
    assert recovery["mismatch_detail"] == "description_changed"
    assert recovery["terminal"] is True
    assert result["pending_execution"] is None
    assert result["planning_result"]["plan"] is None
    assert result["execution_result"] is None
    assert result["status"] == "done"


def test_t21a_description_only_change_during_the_input_pause_fails_closed(tmp_path: Path) -> None:
    graph, reg, rt = _recovery_paused(tmp_path)
    _swap_binding_generic(reg, description="reworded during the pause")  # same binding_id + schema

    result = _resume(graph, "t21", {"path": "/data"})

    _assert_description_mismatch(result)
    assert rt.calls == []


def test_t21_recovery_snapshot_carries_the_description(tmp_path: Path) -> None:
    graph, reg, rt = _recovery_paused(tmp_path)
    result = _resume(graph, "t21", {"path": "/data"})

    assert result["planning_result"]["selected_description"] == "orig description"
    assert result["execution_input_recovery"]["expected_description"] == "orig description"
    assert result["execution_input_recovery"]["outcome"] == "supplied"
    assert result["execution_result"]["status"] == "completed"  # unchanged: no false mismatch
    assert len(rt.calls) == 1


def test_t21_identical_reregistration_during_the_input_pause_is_not_a_mismatch(tmp_path: Path) -> None:
    graph, reg, rt = _recovery_paused(tmp_path)
    reg.register_binding(dataclasses.replace(_current(reg, _SKILL)))

    result = _resume(graph, "t21", {"path": "/data"})

    assert result["execution_input_recovery"]["outcome"] == "supplied"
    assert len(rt.calls) == 1


def test_t21b_description_change_during_the_second_pause_of_a_chain(tmp_path: Path) -> None:
    reg = ExecutionBindingRegistry()
    _CC._register(reg, "trt-perf-analysis", description="TensorRT layer analysis")
    rt_b = _CC._register(
        reg, "bench-tool-b", description="Generic benchmark tool", input_schema=_PATH_REQUIRED
    )
    graph = _CC()._graph_for(tmp_path, reg, skill_ids=_CC._IDS)
    first = _start(graph, _PLANNING_TASK, "t21b")
    assert first["__interrupt__"][0].value["type"] == "choose_candidate"
    second = _resume(graph, "t21b", "bench-tool-b")
    assert second["__interrupt__"][0].value["type"] == "provide_execution_inputs"
    reg.register_binding(
        dataclasses.replace(_current(reg, "bench-tool-b"), description="changed in pause two")
    )

    result = _resume(graph, "t21b", {"path": "/data"})

    assert result["candidate_selection"]["terminal"] is False  # the first pause was fine
    _assert_description_mismatch(result)
    assert rt_b.calls == []


def test_t21c_an_absent_description_snapshot_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_plan = workflow.plan_execution

    def no_description(*args: Any, **kwargs: Any):
        return dataclasses.replace(real_plan(*args, **kwargs), selected_description=None)

    monkeypatch.setattr(workflow, "plan_execution", no_description)
    graph, reg, rt = _recovery_paused(tmp_path)

    result = _resume(graph, "t21", {"path": "/data"})

    _assert_description_mismatch(result)  # "nothing to compare" is not "unchanged"
    assert rt.calls == []


# ── extra: caller-supplied plan on an `allowed` binding still runs ────────


def test_allowed_binding_workflow_still_completes_and_carries_a_pin(tmp_path: Path) -> None:
    reg = ExecutionBindingRegistry()
    rt = _T._register(reg, _SKILL, approval_policy="allowed")
    graph = _T()._graph_for(tmp_path, reg, skill_ids=(_SKILL,))

    result = _start(graph, _PLANNING_TASK, "allowed-1")

    assert result["approval_decision"] == "not_required"
    assert result["execution_result"]["status"] == "completed"
    assert result["pending_execution"]["execution_pin"] == reg.pin(_SKILL) or canonical_json(
        result["pending_execution"]["execution_pin"]
    ) == canonical_json(reg.pin(_SKILL))
    assert len(rt.calls) == 1
