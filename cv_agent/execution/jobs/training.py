"""
cv_agent.execution.jobs.training — approval-gated, provenance-complete training jobs (ADR-0019).

Responsibility: wrap the generic JobExecutor (ADR-0013) with the training-specific rules that
the executor must not know: a request that cannot be built without the [P§25] reproducibility
fields and a cost estimate, an explicit owner approval reference that is checked BEFORE the
executor is called, an explicit lifecycle with a fixed transition table, and a result that
distinguishes "the process finished" from "the candidate is evidence".

Does NOT own: spawning processes (JobRuntime), pin/host checks (JobExecutor), judging a
candidate against its baseline (cv_agent.experiments.acceptance), or minting approvals
(docs/APPROVALS.md). Its only dependency on cv_agent.experiments is the narrow ADR-0019 §2
exception: ``TrainingJobController.for_repository`` imports ``require_clean_worktree`` (ADR-0016)
inside that function, so the HEAD check is reused, not duplicated. Experiments never imports execution.

No real training runtime exists in this change. Nothing here starts a GPU workload by itself.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping

from cv_agent.execution.host import HostRequirement
from cv_agent.execution.jobs.executor import JobExecutor
from cv_agent.execution.jobs.models import JobHandle, JobOutcome, JobResourceMetadata
from cv_agent.execution.models import SkillExecutionRequest
from cv_agent.skills.models import Skill

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_EXP_ID_RE = re.compile(r"^EXP-\d{8}-\d{2}$")
SUPPORTED_APPROVAL_SCOPE = "single run"
"""docs/APPROVALS.md also allows "N runs" and "until date"; this layer supports one run only."""
_ISSUER = object()
"""Controller-only token: TrainingJob and TrainingResult cannot be built in any state from outside."""

TrainingState = Literal[
    "refused", "started", "running", "training_completed", "failed", "cancelled"
]
"""
- refused: preflight, approval, pin or host check failed; no process was started. Terminal.
- started / running: the executor started the job; running once a poll confirmed it.
- training_completed: process exit 0 AND at least one artifact. NOT "accepted": the candidate
  is evidence only after it has been evaluated and compared (cv_agent.experiments.acceptance).
- failed: start raised, exit non-zero, no artifacts, or poll/collect raised. Terminal.
- cancelled: the runtime reported cancelled. Terminal.
"""

_TERMINAL: frozenset[TrainingState] = frozenset(
    {"refused", "training_completed", "failed", "cancelled"}
)
_TRANSITIONS: Mapping[TrainingState, frozenset[TrainingState]] = MappingProxyType(
    {
        "started": frozenset({"running", "training_completed", "failed", "cancelled"}),
        "running": frozenset({"training_completed", "failed", "cancelled"}),
        "refused": frozenset(),
        "training_completed": frozenset(),
        "failed": frozenset(),
        "cancelled": frozenset(),
    }
)


class InvalidTransition(RuntimeError):
    """Raised when a lifecycle move is not in the transition table."""


def _nonblank(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string, got {value!r}")


@dataclass(frozen=True)
class CostEstimate:
    """The estimate docs/APPROVALS.md requires BEFORE asking: 'May I train?' is not a request."""

    gpu_hours: float
    wall_hours: float
    storage_gb: float
    basis: str
    """How the numbers were derived (e.g. the earlier run they were scaled from)."""

    def __post_init__(self) -> None:
        for name in ("gpu_hours", "wall_hours", "storage_gb"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"CostEstimate.{name} must be a finite number > 0, got {value!r}")
        _nonblank(self.basis, "CostEstimate.basis")


@dataclass(frozen=True)
class TrainingApproval:
    """An owner approval, recorded not minted, bound to one experiment, a scope and a cost ceiling."""

    approval_ref: str
    approved_by: str
    binding_pin: Mapping[str, Any]
    """The execution pin the approval was granted for (ADR-0009 §14); the executor verifies it."""
    experiment_id: str
    """The one experiment this approval authorizes (non-transferable, docs/APPROVALS.md)."""
    scope: str
    approved_cost: CostEstimate
    """The estimate presented when asking; its gpu_hours and wall_hours are the approved ceiling."""

    def __post_init__(self) -> None:
        _nonblank(self.approval_ref, "TrainingApproval.approval_ref")
        _nonblank(self.approved_by, "TrainingApproval.approved_by")
        if not self.binding_pin:
            raise ValueError("TrainingApproval.binding_pin is required (approval must bind to a snapshot)")
        if not _EXP_ID_RE.match(self.experiment_id or ""):
            raise ValueError(f"TrainingApproval.experiment_id must match EXP-YYYYMMDD-NN, got {self.experiment_id!r}")
        _nonblank(self.scope, "TrainingApproval.scope")
        if not isinstance(self.approved_cost, CostEstimate):
            raise ValueError("TrainingApproval.approved_cost must be the CostEstimate that was presented")


@dataclass(frozen=True)
class TrainingJobRequest:
    """
    Everything needed to reproduce a training run ([P§25]). Cannot be constructed incomplete, so
    a result derived from it can never be missing provenance.
    """

    experiment_id: str
    baseline_id: str
    commit: str
    dataset_version: str
    model: str
    precision: str
    hardware_target: str
    seed: int
    config: Mapping[str, Any]
    """Hyperparameters, augmentations, resolution, epochs, optimizer: copied and frozen."""
    cost: CostEstimate
    host_requirement: HostRequirement

    def __post_init__(self) -> None:
        if not _EXP_ID_RE.match(self.experiment_id or ""):
            raise ValueError(f"experiment_id must match EXP-YYYYMMDD-NN, got {self.experiment_id!r}")
        if self.baseline_id != "SELF" and not _EXP_ID_RE.match(self.baseline_id or ""):
            raise ValueError(f"baseline_id must be 'SELF' or EXP-YYYYMMDD-NN, got {self.baseline_id!r}")
        if self.baseline_id == self.experiment_id:
            raise ValueError("baseline_id must name a different experiment (or 'SELF')")
        if not _SHA_RE.match(self.commit or ""):
            raise ValueError(f"commit must be a 40-character lowercase hex SHA, got {self.commit!r}")
        for name in ("dataset_version", "model", "precision", "hardware_target"):
            _nonblank(getattr(self, name), name)
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError(f"seed must be an int, got {self.seed!r}")
        if not self.config:
            raise ValueError("config must be a non-empty mapping")
        try:
            json.dumps(dict(self.config), sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"config must be JSON-serialisable: {exc}") from exc
        if not isinstance(self.cost, CostEstimate):
            raise ValueError("cost must be a CostEstimate")
        object.__setattr__(
            self, "config", MappingProxyType(json.loads(json.dumps(dict(self.config))))
        )

    def provenance(self, approval_ref: str | None) -> dict[str, Any]:
        """The immutable snapshot recorded with every result."""
        host = self.host_requirement
        return {
            "experiment_id": self.experiment_id,
            "approval_ref": approval_ref,
            "host_requirement": {"os": host.os, "gpu_vendor": host.gpu_vendor, "min_vram_mb": host.min_vram_mb},
            "baseline_id": self.baseline_id,
            "commit": self.commit,
            "dataset_version": self.dataset_version,
            "model": self.model,
            "precision": self.precision,
            "hardware_target": self.hardware_target,
            "seed": self.seed,
            "config": json.loads(json.dumps(dict(self.config))),
            "cost_estimate": {
                "gpu_hours": self.cost.gpu_hours,
                "wall_hours": self.cost.wall_hours,
                "storage_gb": self.cost.storage_gb,
                "basis": self.cost.basis,
            },
        }


@dataclass(frozen=True)
class TrainingResult:
    experiment_id: str
    state: TrainingState
    provenance: Mapping[str, Any]
    approval_ref: str | None
    job_id: str | None
    reasons: tuple[str, ...] = ()
    artifacts: Mapping[str, str] = field(default_factory=dict)
    resources: JobResourceMetadata = field(default_factory=JobResourceMetadata)
    evaluation_required: bool = True
    """Always True: a finished job is not a result until evaluated against the baseline."""
    _issuer: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._issuer is not _ISSUER:
            raise TypeError("TrainingResult is created only by TrainingJob.result()")

    @property
    def terminal(self) -> bool:
        return self.state in _TERMINAL

    @property
    def ready_for_evaluation(self) -> bool:
        """True only for a completed job with a checkpoint and complete provenance."""
        return (
            self.state == "training_completed"
            and bool(self.artifacts)
            and self.approval_ref is not None
            and bool(self.provenance.get("commit"))
        )


class TrainingJob:
    """One training job's lifecycle. Moves only along the transition table."""

    def __init__(
        self,
        request: TrainingJobRequest,
        approval: TrainingApproval | None,
        executor: JobExecutor,
        handle: JobHandle | None,
        state: TrainingState,
        reasons: tuple[str, ...] = (),
        *,
        _issuer: object = None,
    ) -> None:
        if _issuer is not _ISSUER:
            raise TypeError("TrainingJob is created only by TrainingJobController.start()")
        self._request = request
        self._approval = approval
        self._executor = executor
        self._handle = handle
        self._state: TrainingState = state
        self._reasons: list[str] = list(reasons)
        self._outcome: JobOutcome | None = None
        self.cancel_requested = False

    @property
    def state(self) -> TrainingState:
        return self._state

    def _move(self, new: TrainingState) -> None:
        if new == self._state:
            return
        if new not in _TRANSITIONS[self._state]:
            raise InvalidTransition(f"{self._state!r} -> {new!r} is not allowed")
        self._state = new

    def poll(self) -> TrainingState:
        """Advance from the runtime's status. Never raises for runtime faults; they become 'failed'."""
        if self._state in _TERMINAL or self._handle is None:
            return self._state
        try:
            status = self._executor.poll_job(self._handle)
        except Exception as exc:  # noqa: BLE001
            self._reasons.append(f"poll raised: {exc}")
            self._move("failed")
            return self._state
        if status == "running":
            self._move("running")
            return self._state
        self._move(self._settle(status))
        return self._state

    def _settle(self, status: str) -> TrainingState:
        """Collect once the runtime reports a terminal status, then choose the final state."""
        assert self._handle is not None
        try:
            self._outcome = self._executor.collect_job(self._handle)
        except Exception as exc:  # noqa: BLE001
            self._reasons.append(f"collect raised: {exc}")
            return "cancelled" if status == "cancelled" else "failed"
        if status == "cancelled":
            return "cancelled"
        outcome = self._outcome
        if status == "failed" or not outcome.success or outcome.exit_code not in (0, None):
            self._reasons.append("process did not report success")
            return "failed"
        if not outcome.artifacts:
            self._reasons.append("no checkpoint artifact was produced")
            return "failed"
        return "training_completed"

    def cancel(self) -> bool:
        """Request cancellation. No-op on terminal jobs. The state changes when poll() observes it."""
        if self._state in _TERMINAL or self._handle is None:
            return False
        try:
            self._executor.cancel_job(self._handle)
        except Exception as exc:  # noqa: BLE001
            self._reasons.append(f"cancel raised: {exc}")
            return False
        self.cancel_requested = True  # only once the runtime accepted the request
        return True

    def result(self) -> TrainingResult:
        outcome = self._outcome
        reasons = list(self._reasons)
        approval_ref = self._approval.approval_ref if self._approval else None
        if outcome is not None and outcome.error_message:
            reasons.append(outcome.error_message)
        return TrainingResult(
            experiment_id=self._request.experiment_id,
            state=self._state,
            provenance=MappingProxyType(self._request.provenance(approval_ref)),
            approval_ref=approval_ref,
            job_id=self._handle.job_id if self._handle else None,
            reasons=tuple(reasons),
            artifacts=MappingProxyType(dict(outcome.artifacts)) if outcome else MappingProxyType({}),
            resources=outcome.resources if outcome else JobResourceMetadata(),
            _issuer=_ISSUER,
        )


class TrainingJobController:
    """Preflight, approval gate and start for training jobs. Starts nothing without approval."""

    def __init__(
        self,
        executor: JobExecutor,
        skill: Skill,
        *,
        head_commit_for_tests: Callable[[], str],
    ) -> None:
        """
        Tests only: ``head_commit_for_tests`` stands in for the real HEAD check. Production code
        uses ``for_repository``, which wires require_clean_worktree (ADR-0016).
        """
        self._executor = executor
        self._skill = skill
        self._head_commit = head_commit_for_tests

    @classmethod
    def for_repository(cls, executor: JobExecutor, skill: Skill, repo_root: Path) -> TrainingJobController:
        """The default controller: HEAD must be clean and equal to the request's commit."""
        from cv_agent.experiments.provenance import require_clean_worktree  # ADR-0019 §2 exception

        root = Path(repo_root)
        return cls(executor, skill, head_commit_for_tests=lambda: require_clean_worktree(root))

    def preflight(self, request: TrainingJobRequest, approval: TrainingApproval | None) -> list[str]:
        """Every problem that blocks a start. Empty list means the gate is open."""
        problems: list[str] = []
        if approval is None:
            problems.append(
                "explicit owner approval is required before any training run ([P§24]); none supplied"
            )
        else:
            if approval.scope != SUPPORTED_APPROVAL_SCOPE:
                problems.append(
                    f"unsupported approval scope {approval.scope!r}; only {SUPPORTED_APPROVAL_SCOPE!r} is supported"
                )
            if approval.experiment_id != request.experiment_id:
                problems.append(
                    f"approval {approval.approval_ref} is for {approval.experiment_id}, not "
                    f"{request.experiment_id}; an approval is non-transferable (docs/APPROVALS.md)"
                )
            for name in ("gpu_hours", "wall_hours"):
                asked, ceiling = getattr(request.cost, name), getattr(approval.approved_cost, name)
                if asked > ceiling:
                    problems.append(f"request {name} {asked} exceeds the approved ceiling {ceiling}")
        if not self._executor.can_start(self._skill.skill_id):
            problems.append(
                f"no verified binding with a registered job runtime for skill '{self._skill.skill_id}'"
            )
        try:
            head = self._head_commit()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"worktree provenance check failed: {exc}")
        else:
            if head != request.commit:
                problems.append(
                    f"request commit {request.commit} does not match HEAD {head}; "
                    "the recorded code must be the code that runs"
                )
        return problems

    def start(self, request: TrainingJobRequest, approval: TrainingApproval | None) -> TrainingJob:
        """Return a TrainingJob. State is 'refused' (nothing started) or 'started'/'failed'."""
        problems = self.preflight(request, approval)
        if problems:
            return TrainingJob(request, approval, self._executor, None, "refused", tuple(problems), _issuer=_ISSUER)
        assert approval is not None
        exec_request = SkillExecutionRequest(
            inputs={
                "experiment_id": request.experiment_id,
                "seed": request.seed,
                "config": dict(request.config),
                "model": request.model,
                "dataset_version": request.dataset_version,
                "precision": request.precision,
            },
            task=f"training run {request.experiment_id}",
            requested_by=approval.approved_by,
            approved=True,
            expected_binding_pin=dict(approval.binding_pin),
        )
        handle, job_result = self._executor.start_job(
            self._skill, exec_request, request.host_requirement
        )
        if handle is None:
            reason = job_result.error.message if job_result.error else job_result.status
            state: TrainingState = "failed" if job_result.status == "failed" else "refused"
            return TrainingJob(
                request, approval, self._executor, None, state,
                (f"{job_result.status}: {reason}",), _issuer=_ISSUER,
            )
        return TrainingJob(request, approval, self._executor, handle, "started", _issuer=_ISSUER)
