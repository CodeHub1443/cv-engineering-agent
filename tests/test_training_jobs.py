"""
Tests for cv_agent.execution.jobs.training (ADR-0019, issue #76).

Deterministic: a fake JobRuntime, a fake host verifier, and a fake commit callable. No GPU,
no subprocess, no real training. The fake runtime counts start() calls so the approval-gate
tests can prove nothing was started.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pytest

from cv_agent.execution.binding import ExecutionBinding, ExecutionBindingRegistry
from cv_agent.execution.host import HostProfile, HostRequirement, LinuxNvidiaHostVerifier
from cv_agent.execution.jobs.executor import JobExecutor
from cv_agent.execution.jobs.models import JobHandle, JobOutcome, JobResourceMetadata
from cv_agent.execution.jobs.training import (
    CostEstimate,
    InvalidTransition,
    TrainingApproval,
    TrainingJob,
    TrainingJobController,
    TrainingJobRequest,
)
from cv_agent.execution.models import SkillExecutionRequest
from cv_agent.skills.models import Skill

SHA = "b" * 40
SKILL_ID = "train-skill"
RUNTIME_ID = "fake-train-runtime"


@dataclass
class FakeTrainRuntime:
    runtime_id: str = RUNTIME_ID
    poll_sequence: list[str] = field(default_factory=lambda: ["running", "completed"])
    start_raises: Exception | None = None
    poll_raises: Exception | None = None
    collect_raises: Exception | None = None
    outcome: JobOutcome | None = None
    start_calls: int = 0
    cancel_calls: int = 0
    _i: int = 0
    _cancelled: bool = False

    def start(self, skill: Skill, request: SkillExecutionRequest) -> JobHandle:
        self.start_calls += 1
        if self.start_raises is not None:
            raise self.start_raises
        return JobHandle(job_id="train-001", runtime_id=self.runtime_id, started_at="2026-10-14T00:00:00+00:00")

    def poll(self, handle: JobHandle) -> Literal["running", "completed", "failed", "cancelled"]:
        if self.poll_raises is not None:
            raise self.poll_raises
        seq = self.poll_sequence
        status = seq[min(self._i, len(seq) - 1)]
        self._i += 1
        return status  # type: ignore[return-value]

    def cancel(self, handle: JobHandle) -> None:
        self.cancel_calls += 1
        self._cancelled = True
        self._i = 0
        self.poll_sequence = ["cancelled"]

    def collect(self, handle: JobHandle) -> JobOutcome:
        if self.collect_raises is not None:
            raise self.collect_raises
        if self.outcome is not None:
            return self.outcome
        if self._cancelled:
            return JobOutcome(success=False, exit_code=None, stdout=None, stderr=None, error_message="cancelled")
        return JobOutcome(
            success=True, exit_code=0, stdout="ok", stderr="",
            artifacts={"best.pt": "/runs/train-001/best.pt"},
            resources=JobResourceMetadata(wall_time_seconds=10.0, gpu_hours=0.003),
        )


def _skill() -> Skill:
    return Skill(skill_id=SKILL_ID, name=SKILL_ID, description="fake", source="fixture",
                 location="/fixtures/train/SKILL.md")


def _binding() -> ExecutionBinding:
    return ExecutionBinding(skill_id=SKILL_ID, binding_id="b-train", runtime_id=RUNTIME_ID,
                            approval_policy="approval_required", verified=True)


def _verifier() -> LinuxNvidiaHostVerifier:
    return LinuxNvidiaHostVerifier(
        profile=HostProfile(os="linux", gpu_available=True, gpu_vendor="nvidia", driver_version="535")
    )


def _request(**over: object) -> TrainingJobRequest:
    fields: dict[str, object] = dict(
        experiment_id="EXP-20261014-01",
        baseline_id="EXP-20261004-01",
        commit=SHA,
        dataset_version="coco-val2017-5k",
        model="yolo11n",
        precision="FP32",
        hardware_target="RTX 3060 12GB",
        seed=0,
        config={"epochs": 10, "imgsz": 640, "lr0": 0.01},
        cost=CostEstimate(gpu_hours=2.0, wall_hours=2.5, storage_gb=1.0, basis="scaled from EXP-20261004-01 wall time"),
        host_requirement=HostRequirement(os="linux", gpu_vendor="nvidia"),
    )
    fields.update(over)
    return TrainingJobRequest(**fields)  # type: ignore[arg-type]


def _setup(
    runtime: FakeTrainRuntime | None = None,
    head: str = SHA,
    head_raises: Exception | None = None,
    verifier: LinuxNvidiaHostVerifier | None = None,
    register_binding: bool = True,
) -> tuple[TrainingJobController, FakeTrainRuntime, TrainingApproval]:
    rt = runtime or FakeTrainRuntime()
    reg = ExecutionBindingRegistry()
    binding = _binding()
    if register_binding:
        reg.register_binding(binding)
    executor = JobExecutor(reg, {rt.runtime_id: rt}, verifier or _verifier())

    def head_commit() -> str:
        if head_raises is not None:
            raise head_raises
        return head

    pin = binding.pin()
    reg_entry = reg.get_runtime_registration(RUNTIME_ID)
    approval = TrainingApproval(
        approval_ref="OWNER-APPROVAL-EXP-20261014-01",
        approved_by="owner",
        binding_pin={"binding": pin, "runtime_generation": reg_entry[1] if reg_entry else None},
    )
    return TrainingJobController(executor, _skill(), head_commit), rt, approval


# --- request validation / provenance completeness ------------------------------------------

@pytest.mark.parametrize(
    "over",
    [
        {"experiment_id": "run-1"},
        {"baseline_id": "nope"},
        {"baseline_id": "EXP-20261014-01"},
        {"commit": "abc"},
        {"commit": "B" * 40},
        {"dataset_version": " "},
        {"model": ""},
        {"precision": ""},
        {"hardware_target": ""},
        {"seed": True},
        {"seed": "0"},
        {"config": {}},
        {"config": {"x": object()}},
    ],
)
def test_incomplete_request_cannot_be_constructed(over: dict) -> None:
    with pytest.raises(ValueError):
        _request(**over)


@pytest.mark.parametrize("bad", [0, -1.0, float("nan"), float("inf"), True])
def test_cost_estimate_rejects_invalid_numbers(bad: object) -> None:
    with pytest.raises(ValueError):
        CostEstimate(gpu_hours=bad, wall_hours=1.0, storage_gb=1.0, basis="b")  # type: ignore[arg-type]


def test_cost_estimate_requires_basis() -> None:
    with pytest.raises(ValueError):
        CostEstimate(gpu_hours=1.0, wall_hours=1.0, storage_gb=1.0, basis=" ")


def test_approval_requires_reference_and_pin() -> None:
    with pytest.raises(ValueError):
        TrainingApproval(approval_ref=" ", approved_by="owner", binding_pin={"a": 1})
    with pytest.raises(ValueError):
        TrainingApproval(approval_ref="X", approved_by="owner", binding_pin={})


def test_request_config_is_frozen_copy() -> None:
    cfg = {"epochs": 10}
    req = _request(config=cfg)
    cfg["epochs"] = 999
    assert req.config["epochs"] == 10
    with pytest.raises(TypeError):
        req.config["epochs"] = 1  # type: ignore[index]


def test_provenance_snapshot_is_complete() -> None:
    ctrl, _, approval = _setup()
    job = ctrl.start(_request(), approval)
    prov = job.result().provenance
    for key in ("experiment_id", "baseline_id", "commit", "dataset_version", "model", "precision",
                "hardware_target", "seed", "config", "cost_estimate"):
        assert key in prov and prov[key] not in (None, "")
    assert prov["commit"] == SHA
    assert job.result().approval_ref == "OWNER-APPROVAL-EXP-20261014-01"


# --- approval gate ---------------------------------------------------------------------------

def test_no_approval_means_refused_and_nothing_started() -> None:
    ctrl, rt, _ = _setup()
    job = ctrl.start(_request(), None)
    assert job.state == "refused"
    assert rt.start_calls == 0
    assert any("approval" in r for r in job.result().reasons)
    assert job.result().approval_ref is None
    assert not job.result().ready_for_evaluation


def test_stale_pin_is_rejected_by_executor_and_nothing_started() -> None:
    ctrl, rt, approval = _setup()
    bad = TrainingApproval(approval_ref="X", approved_by="owner", binding_pin={"binding": {}, "runtime_generation": 99})
    job = ctrl.start(_request(), bad)
    assert job.state == "refused"
    assert rt.start_calls == 0
    assert any("rejected" in r for r in job.result().reasons)


def test_commit_mismatch_refuses() -> None:
    ctrl, rt, approval = _setup(head="c" * 40)
    job = ctrl.start(_request(), approval)
    assert job.state == "refused" and rt.start_calls == 0
    assert any("does not match HEAD" in r for r in job.result().reasons)


def test_dirty_worktree_refuses() -> None:
    ctrl, rt, approval = _setup(head_raises=RuntimeError("refusing to produce evidence from a dirty worktree"))
    job = ctrl.start(_request(), approval)
    assert job.state == "refused" and rt.start_calls == 0
    assert any("dirty worktree" in r for r in job.result().reasons)


def test_unregistered_binding_refuses() -> None:
    ctrl, rt, approval = _setup(register_binding=False)
    job = ctrl.start(_request(), approval)
    assert job.state == "refused" and rt.start_calls == 0


def test_host_mismatch_refuses() -> None:
    bad_host = LinuxNvidiaHostVerifier(
        profile=HostProfile(os="windows", gpu_available=False, gpu_vendor=None, driver_version=None)
    )
    ctrl, rt, approval = _setup(verifier=bad_host)
    job = ctrl.start(_request(), approval)
    assert job.state == "refused" and rt.start_calls == 0
    assert any("host_mismatch" in r for r in job.result().reasons)


# --- lifecycle -------------------------------------------------------------------------------

def test_happy_path_started_running_completed() -> None:
    ctrl, rt, approval = _setup()
    job = ctrl.start(_request(), approval)
    assert job.state == "started" and rt.start_calls == 1
    assert job.poll() == "running"
    assert job.poll() == "training_completed"
    result = job.result()
    assert result.terminal and result.ready_for_evaluation
    assert result.artifacts == {"best.pt": "/runs/train-001/best.pt"}
    assert result.evaluation_required is True
    assert result.resources.gpu_hours == 0.003


def test_completed_is_not_accepted_state() -> None:
    ctrl, _, approval = _setup()
    job = ctrl.start(_request(), approval)
    job.poll()
    job.poll()
    assert job.state == "training_completed"
    assert job.result().evaluation_required


def test_poll_after_terminal_is_stable() -> None:
    ctrl, rt, approval = _setup()
    job = ctrl.start(_request(), approval)
    job.poll()
    job.poll()
    before = rt._i
    assert job.poll() == "training_completed"
    assert rt._i == before  # runtime not polled again


def test_runtime_start_failure_is_failed_with_reason() -> None:
    ctrl, rt, approval = _setup(FakeTrainRuntime(start_raises=RuntimeError("cuda oom at launch")))
    job = ctrl.start(_request(), approval)
    assert job.state == "failed"
    assert any("cuda oom" in r for r in job.result().reasons)
    assert not job.result().ready_for_evaluation


def test_non_zero_exit_is_failed() -> None:
    out = JobOutcome(success=False, exit_code=1, stdout="", stderr="boom", error_message="exit 1")
    ctrl, _, approval = _setup(FakeTrainRuntime(poll_sequence=["failed"], outcome=out))
    job = ctrl.start(_request(), approval)
    assert job.poll() == "failed"
    assert "exit 1" in job.result().reasons


def test_success_without_artifacts_is_failed_not_evidence() -> None:
    out = JobOutcome(success=True, exit_code=0, stdout="", stderr="", artifacts={})
    ctrl, _, approval = _setup(FakeTrainRuntime(poll_sequence=["completed"], outcome=out))
    job = ctrl.start(_request(), approval)
    assert job.poll() == "failed"
    assert any("no checkpoint" in r for r in job.result().reasons)
    assert not job.result().ready_for_evaluation


def test_poll_exception_becomes_failed() -> None:
    ctrl, _, approval = _setup(FakeTrainRuntime(poll_raises=RuntimeError("process vanished")))
    job = ctrl.start(_request(), approval)
    assert job.poll() == "failed"
    assert any("process vanished" in r for r in job.result().reasons)


def test_collect_exception_after_completed_is_failed() -> None:
    ctrl, _, approval = _setup(FakeTrainRuntime(poll_sequence=["completed"], collect_raises=OSError("disk gone")))
    job = ctrl.start(_request(), approval)
    assert job.poll() == "failed"
    assert not job.result().ready_for_evaluation


def test_cancel_from_started_then_poll_observes_cancelled() -> None:
    ctrl, rt, approval = _setup()
    job = ctrl.start(_request(), approval)
    assert job.cancel() is True
    assert job.cancel_requested and rt.cancel_calls == 1
    assert job.state == "started"  # not terminal until the runtime confirms
    assert job.poll() == "cancelled"
    assert not job.result().ready_for_evaluation


def test_cancel_from_running() -> None:
    ctrl, rt, approval = _setup()
    job = ctrl.start(_request(), approval)
    job.poll()
    assert job.state == "running"
    assert job.cancel() is True
    assert job.poll() == "cancelled"


def test_cancel_on_terminal_or_refused_is_noop() -> None:
    ctrl, rt, approval = _setup()
    refused = ctrl.start(_request(), None)
    assert refused.cancel() is False and rt.cancel_calls == 0
    job = ctrl.start(_request(), approval)
    job.poll()
    job.poll()
    assert job.cancel() is False and rt.cancel_calls == 0


def test_invalid_transition_raises() -> None:
    ctrl, _, approval = _setup()
    job = ctrl.start(_request(), approval)
    job.poll()
    job.poll()
    assert isinstance(job, TrainingJob)
    with pytest.raises(InvalidTransition):
        job._move("running")  # terminal -> running is not in the table
    refused = ctrl.start(_request(), None)
    with pytest.raises(InvalidTransition):
        refused._move("started")


def test_started_cannot_jump_back_from_running() -> None:
    ctrl, _, approval = _setup()
    job = ctrl.start(_request(), approval)
    job.poll()
    with pytest.raises(InvalidTransition):
        job._move("started")


def test_controller_module_does_not_import_experiments_layer() -> None:
    import ast

    import cv_agent.execution.jobs.training as mod

    tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
    imported = [
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [None])
    ]
    assert not [m for m in imported if m and m.startswith("cv_agent.experiments")]
