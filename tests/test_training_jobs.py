"""
Tests for cv_agent.execution.jobs.training (ADR-0019, issue #76).

Deterministic: a fake JobRuntime, a fake host verifier, and a fake commit callable. No GPU,
no subprocess, no real training. The fake runtime counts start() calls so the approval-gate
tests can prove nothing was started.
"""

from __future__ import annotations

import ast
import dataclasses
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
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
    TrainingResult,
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
    cancel_raises: Exception | None = None
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
        if self.cancel_raises is not None:
            raise self.cancel_raises
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


COST = CostEstimate(gpu_hours=2.0, wall_hours=2.5, storage_gb=1.0, basis="scaled from EXP-20261004-01 wall time")


def _approval(binding_pin: dict, **over: object) -> TrainingApproval:
    fields: dict[str, object] = dict(
        approval_ref="OWNER-APPROVAL-EXP-20261014-01", approved_by="owner", binding_pin=binding_pin,
        experiment_id="EXP-20261014-01", scope="single run", approved_cost=COST,
    )
    fields.update(over)
    return TrainingApproval(**fields)  # type: ignore[arg-type]


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
        cost=COST,
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
    repo_root: Path | None = None,
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
    approval = _approval({"binding": pin, "runtime_generation": reg_entry[1] if reg_entry else None})
    if repo_root is not None:
        return TrainingJobController.for_repository(executor, _skill(), repo_root), rt, approval
    return TrainingJobController(executor, _skill(), head_commit_for_tests=head_commit), rt, approval


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
    for over in ({"approval_ref": " "}, {"binding_pin": {}}, {"experiment_id": "run-1"}, {"scope": " "},
                 {"approved_cost": 2.0}):
        with pytest.raises(ValueError):
            _approval(**{"binding_pin": {"a": 1}, **over})


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
                "hardware_target", "seed", "config", "cost_estimate", "approval_ref", "host_requirement"):
        assert key in prov and prov[key] not in (None, "")
    assert prov["commit"] == SHA
    assert prov["approval_ref"] == "OWNER-APPROVAL-EXP-20261014-01"
    assert prov["host_requirement"] == {"os": "linux", "gpu_vendor": "nvidia", "min_vram_mb": None}
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
    bad = _approval({"binding": {}, "runtime_generation": 99})
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


def _experiments_imports(source: str) -> tuple[list[str], int]:
    """(violations, allowed count). Allowed: exactly ``from cv_agent.experiments.provenance import
    require_clean_worktree`` inside TrainingJobController.for_repository (ADR-0019 §2 exception)."""
    tree = ast.parse(source)
    allowed: set[int] = set()
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == "TrainingJobController":
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "for_repository":
                    allowed |= {
                        id(n) for n in ast.walk(fn)
                        if isinstance(n, ast.ImportFrom) and n.module == "cv_agent.experiments.provenance"
                        and n.level == 0
                        and [(a.name, a.asname) for a in n.names] == [("require_clean_worktree", None)]
                    }
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            hit = "experiments" in mod.split(".") or (
                mod == "cv_agent" and any(a.name == "experiments" for a in node.names))
        elif isinstance(node, ast.Import):
            hit = any(a.name.startswith("cv_agent.experiments") for a in node.names)
        else:
            continue
        if hit and id(node) not in allowed:
            violations.append(ast.unparse(node))
    return violations, len(allowed)


def test_training_module_imports_only_the_allowed_provenance_symbol() -> None:
    import cv_agent.execution.jobs.training as mod

    violations, allowed = _experiments_imports(Path(mod.__file__).read_text(encoding="utf-8"))
    assert violations == [] and allowed == 1


_FACTORY = "class TrainingJobController:\n    @classmethod\n    def for_repository(cls):\n        {}\n"


@pytest.mark.parametrize("source", [
    "from cv_agent.experiments.provenance import require_clean_worktree\n" + _FACTORY.format("pass"),
    _FACTORY.format("from cv_agent.experiments.provenance import current_commit"),
    _FACTORY.format("from cv_agent.experiments.provenance import require_clean_worktree, current_commit"),
    _FACTORY.format("from cv_agent.experiments.provenance import require_clean_worktree as r"),
    _FACTORY.format("import cv_agent.experiments.provenance"),
    _FACTORY.format("from cv_agent.experiments import provenance"),
    _FACTORY.format("from cv_agent import experiments"),
    _FACTORY.format("from ...experiments.provenance import require_clean_worktree"),
    _FACTORY.format("from cv_agent.experiments.acceptance import evaluate_candidate"),
    "class TrainingJobController:\n    def start(self):\n"
    "        from cv_agent.experiments.provenance import require_clean_worktree\n",
])
def test_layering_check_rejects_any_other_experiments_import(source: str) -> None:
    assert _experiments_imports(source)[0]


def test_layering_check_accepts_the_exact_exception() -> None:
    src = _FACTORY.format("from cv_agent.experiments.provenance import require_clean_worktree")
    assert _experiments_imports(src) == ([], 1)


# --- H1: approval bound to experiment, scope and cost ceiling --------------------------------

def test_approval_for_another_experiment_is_refused() -> None:
    ctrl, rt, approval = _setup()
    job = ctrl.start(_request(), dataclasses.replace(approval, experiment_id="EXP-20261014-02"))
    assert job.state == "refused" and rt.start_calls == 0
    assert any("non-transferable" in r for r in job.result().reasons)


@pytest.mark.parametrize("name", ["gpu_hours", "wall_hours"])
def test_cost_above_approved_ceiling_is_refused(name: str) -> None:
    ctrl, rt, approval = _setup()
    cost = dataclasses.replace(COST, **{name: getattr(COST, name) + 0.5})
    job = ctrl.start(_request(cost=cost), approval)
    assert job.state == "refused" and rt.start_calls == 0
    assert any(name in r and "exceeds the approved ceiling" in r for r in job.result().reasons)


def test_unsupported_approval_scope_is_refused() -> None:
    ctrl, rt, approval = _setup()
    job = ctrl.start(_request(), dataclasses.replace(approval, scope="N runs"))
    assert job.state == "refused" and rt.start_calls == 0
    assert any("unsupported approval scope 'N runs'" in r for r in job.result().reasons)


# --- M2: no lifecycle object or result in an arbitrary state from outside --------------------

def test_training_job_cannot_be_built_outside_the_controller() -> None:
    ctrl, _, approval = _setup()
    handle = JobHandle(job_id="x", runtime_id=RUNTIME_ID, started_at="2026-10-14T00:00:00+00:00")
    with pytest.raises(TypeError):
        TrainingJob(_request(), approval, ctrl._executor, handle, "training_completed")


def test_ready_for_evaluation_result_cannot_be_built_directly() -> None:
    with pytest.raises(TypeError):
        TrainingResult(experiment_id="EXP-20261014-01", state="training_completed",
                       provenance={"commit": SHA}, approval_ref="X", job_id="j", artifacts={"best.pt": "/x"})


# --- M3: the real clean-worktree / HEAD check through for_repository -------------------------

def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    (tmp_path / "tracked.txt").write_text("v1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "initial")
    return tmp_path


def test_for_repository_refuses_a_dirty_tree(repo: Path) -> None:
    (repo / "untracked.txt").write_text("x")
    ctrl, rt, approval = _setup(repo_root=repo)
    job = ctrl.start(_request(commit=_git(repo, "rev-parse", "HEAD")), approval)
    assert job.state == "refused" and rt.start_calls == 0
    assert any("dirty worktree" in r for r in job.result().reasons)


def test_for_repository_refuses_a_mismatched_head(repo: Path) -> None:
    ctrl, rt, approval = _setup(repo_root=repo)
    job = ctrl.start(_request(commit=SHA), approval)
    assert job.state == "refused" and rt.start_calls == 0
    assert any("does not match HEAD" in r for r in job.result().reasons)


def test_for_repository_clean_matching_head_passes_preflight(repo: Path) -> None:
    ctrl, _, approval = _setup(repo_root=repo)
    assert ctrl.preflight(_request(commit=_git(repo, "rev-parse", "HEAD")), approval) == []


# --- L2: cancel / collect faults -------------------------------------------------------------

def test_collect_exception_after_cancel_is_cancelled_with_reason() -> None:
    ctrl, _, approval = _setup(FakeTrainRuntime(collect_raises=OSError("disk gone")))
    job = ctrl.start(_request(), approval)
    assert job.cancel() is True
    assert job.poll() == "cancelled"
    assert any("collect raised: disk gone" in r for r in job.result().reasons)
    assert not job.result().ready_for_evaluation


def test_cancel_raising_is_reported_and_not_marked_requested() -> None:
    ctrl, _, approval = _setup(FakeTrainRuntime(cancel_raises=RuntimeError("signal failed")))
    job = ctrl.start(_request(), approval)
    assert job.cancel() is False
    assert job.cancel_requested is False and job.state == "started"
    assert any("cancel raised: signal failed" in r for r in job.result().reasons)
