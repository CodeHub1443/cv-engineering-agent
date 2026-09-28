"""
cv_agent.execution.jobs.models — data model for long-running CV job execution.

Analogous to cv_agent.execution.models for synchronous skill execution
(ADR-0009), but for jobs that run as separate OS processes (ADR-0013).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from cv_agent.execution.models import ExecutionError, ExecutionEvidence

JobStatus = Literal[
    "not_submitted",
    "started",
    "running",
    "completed",
    "failed",
    "cancelled",
    "host_mismatch",
    "rejected",
]
"""
Terminal states: completed, failed, cancelled, host_mismatch, rejected.
Non-terminal states: not_submitted, started, running.

- not_submitted: pre-flight check failed before start() was called (no
  binding, unverified binding, no job runtime registered).
- started: process was spawned; not yet confirmed running by a poll().
  This is the first reachable use of the "started" value reserved in
  SkillExecutionStatus since ADR-0009.
- running: confirmed running by at least one successful poll().
- completed: process exited with success (exit code 0).
- failed: process exited with non-zero exit code, raised, or could not start.
- cancelled: was running and was cancelled by the caller.
- host_mismatch: host verification failed — job never started.
- rejected: pin/approval check failed — job never started.
"""

JobErrorCategory = Literal[
    "no_binding",
    "binding_not_verified",
    "approval_denied",
    "binding_mismatch",
    "host_mismatch",
    "runtime_error",
    "cancelled",
]

_TERMINAL_STATUSES: frozenset[JobStatus] = frozenset(
    {"completed", "failed", "cancelled", "host_mismatch", "rejected"}
)


@dataclass(frozen=True)
class JobHandle:
    """
    Opaque reference to a running job. Only the JobRuntime that issued it
    can interpret it; JobExecutor stores it verbatim.
    """

    job_id: str
    """Stable identifier, assigned by the JobRuntime at start time."""
    runtime_id: str
    """The runtime that issued this handle."""
    started_at: str
    """ISO-8601 UTC timestamp of when start() was called."""


@dataclass(frozen=True)
class JobResourceMetadata:
    """
    Resource usage captured at job completion. Fields absent (None) if the
    runtime could not measure them. Maps to ExperimentRecord's hardware/timing
    fields (ADR-0011) — never guessed, only captured.
    """

    wall_time_seconds: float | None = None
    gpu_hours: float | None = None
    peak_vram_mb: float | None = None
    peak_ram_mb: float | None = None
    avg_power_watts: float | None = None
    exit_code: int | None = None


@dataclass(frozen=True)
class JobOutcome:
    """
    Terminal result of a completed, failed, or cancelled job.
    Only present in JobResult when status is completed, failed, or cancelled
    — never for host_mismatch or rejected (the job never started).
    """

    success: bool
    exit_code: int | None
    stdout: str | None
    """Full captured stdout. May be partial on cancellation."""
    stderr: str | None
    """Full captured stderr. May be partial on cancellation."""
    artifacts: dict[str, str] = field(default_factory=dict)
    """name → absolute path of produced artifact file. Empty on failure/cancel."""
    resources: JobResourceMetadata = field(default_factory=JobResourceMetadata)
    error_message: str | None = None


@dataclass(frozen=True)
class JobResult:
    """
    What JobExecutor reports to the orchestration layer.
    Analogous to SkillExecutionResult (ADR-0009) — same design pattern.
    """

    skill_id: str
    job_id: str | None
    """None if the job never reached started (pre-flight failure)."""
    status: JobStatus
    evidence: ExecutionEvidence
    """Reuses cv_agent.execution.models.ExecutionEvidence for provenance."""
    outcome: JobOutcome | None = None
    """Present only for completed/failed/cancelled status."""
    error: ExecutionError | None = None
    """Reuses cv_agent.execution.models.ExecutionError for the error record.
    error.category is a JobErrorCategory value cast as str (both are Literals
    whose values overlap; cast avoids a second error dataclass for identical
    semantics)."""

    @property
    def ok(self) -> bool:
        return self.status == "completed"

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    def as_dict(self) -> dict[str, Any]:
        """Checkpoint-safe serialisation for AgentState.job_result storage."""
        import dataclasses
        return dataclasses.asdict(self)
