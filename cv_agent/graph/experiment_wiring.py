"""
cv_agent.graph.experiment_wiring — JobResult → ExperimentRecord bridge.

Authorized by ADR-0013 §9 ("The graph node that writes the ledger entry
maps JobResult → ExperimentRecord — a later, separate implementation PR")
and ADR-0011 §8 (first revisit trigger: "when CVAgent/the CLI/a training-
execution subsystem is ready to actually write real experiment rows").

Responsibility: mapping a terminal JobResult plus caller-supplied context
into an ExperimentRecord that can be written to the ExperimentLedger. This
module owns the translation, nothing else — it does not control execution,
trigger approval, or call JobRuntime directly.

Layer: orchestration (cv_agent.graph). Imports from the execution layer
(cv_agent.execution.jobs.models) and the memory layer (cv_agent.experiments).
[P§19] — layers stay separate; the orchestration layer is the authorized
bridge between them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from cv_agent.execution.jobs.models import JobResult
from cv_agent.experiments.models import (
    ExperimentRecord,
    ExperimentStatus,
    HardwareInfo,
    MemoryFootprint,
)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ExperimentContext:
    """
    Caller-supplied fields that JobResult alone cannot provide.

    Populated by the graph node from AgentState, the SelectionRecommendation
    (model), and any execution-time metadata available before or at the start
    of the run. None of these are derived from JobOutcome — they must be
    known before the job runs.
    """

    exp_id: str
    """EXP-YYYYMMDD-NN format — validated by ExperimentRecord.__post_init__."""
    baseline_id: str
    """"SELF" for a first baseline; another EXP-YYYYMMDD-NN for a comparison."""
    hypothesis: str
    """Non-blank statement of what this run is testing."""
    success_criteria: str
    """Non-blank, measurable pass/fail criteria stated before the run."""
    model: str | None = None
    """SelectionRecommendation.recommended_candidate_id, if the run follows
    a model-selection proposal."""
    dataset_version: str | None = None
    """DatasetManifest (dataset_id, version) string, if applicable."""
    approval_ref: str | None = None
    """Reference to the approval decision (e.g. job_approval_decision from AgentState)."""
    commit: str | None = None
    """Git commit SHA at run time."""
    hardware_training: str | None = None
    """Execution hardware — in inference/detection context, the GPU that ran the job."""
    hardware_target: str | None = None
    """Deployment target hardware — where the model will ultimately run."""
    notes: str = ""
    """Free-text notes to prefix into the ExperimentRecord's notes field."""


def _map_status(job_status: str) -> ExperimentStatus:
    """
    Maps terminal JobStatus → ExperimentStatus.

    completed  → completed
    failed     → failed
    cancelled  → cancelled
    host_mismatch → failed  (pre-flight: host check blocked the job)
    rejected   → cancelled  (pre-flight: approval/pin check rejected the job)
    """
    mapping: dict[str, ExperimentStatus] = {
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
        "host_mismatch": "failed",
        "rejected": "cancelled",
    }
    return mapping.get(job_status, "failed")


def job_result_to_experiment_record(
    result: JobResult,
    *,
    context: ExperimentContext,
    _now_iso: str | None = None,
) -> ExperimentRecord:
    """
    Map a terminal JobResult + ExperimentContext → ExperimentRecord.

    Must only be called with a terminal JobResult (result.terminal is True).
    Non-terminal results raise ValueError — the ledger node must wait for
    terminal state before calling this (ADR-0013 §9).

    Fields populated from result (where available — never fabricated):
      status        ← result.status  (via _map_status)
      created_at    ← result.evidence.started_at, else now
      completed_at  ← result.evidence.completed_at, else now
      train_time    ← outcome.resources.wall_time_seconds
      gpu_hours     ← outcome.resources.gpu_hours
      power         ← outcome.resources.avg_power_watts
      memory        ← outcome.resources.peak_vram_mb + peak_ram_mb
      failure_analysis ← result.error + outcome.error_message (for non-completed)
      notes         ← artifact paths (JSON), exit code, stdout/stderr summary

    Fields never populated by this function (must come from context or stay None):
      val_metrics, test_metrics, latency, fps — these require actual inference
      measurements the V1 baseline runtime does not yet produce; they must not
      be invented.
    """
    if not result.terminal:
        raise ValueError(
            f"job_result_to_experiment_record requires a terminal JobResult; "
            f"got status={result.status!r}. Non-terminal results must not be "
            "written to the ledger (ADR-0013 §9)."
        )

    now = _now_iso or _now_utc_iso()
    created_at = result.evidence.started_at or now
    completed_at = result.evidence.completed_at or now
    exp_status = _map_status(result.status)
    outcome = result.outcome

    # ── Resource fields from outcome (only what the runtime actually measured) ──
    gpu_hours: float | None = None
    train_time: float | None = None
    power: float | None = None
    memory: MemoryFootprint | None = None

    if outcome is not None:
        res = outcome.resources
        gpu_hours = res.gpu_hours
        train_time = res.wall_time_seconds
        power = res.avg_power_watts
        if res.peak_vram_mb is not None or res.peak_ram_mb is not None:
            memory = MemoryFootprint(
                vram=res.peak_vram_mb if res.peak_vram_mb is not None else 0.0,
                ram=res.peak_ram_mb if res.peak_ram_mb is not None else 0.0,
            )

    # ── HardwareInfo from context (requires both training and target) ──
    hardware: HardwareInfo | None = None
    if context.hardware_training is not None and context.hardware_target is not None:
        hardware = HardwareInfo(
            training=context.hardware_training,
            target=context.hardware_target,
        )

    # ── Failure analysis for non-completed experiments ──
    failure_analysis: str | None = None
    if exp_status in ("failed", "cancelled"):
        parts: list[str] = []
        if result.error is not None:
            parts.append(
                f"[{result.error.category}] {result.error.message}"
            )
        if result.status == "host_mismatch":
            parts.append("Job never started: host verification failed.")
        elif result.status == "rejected":
            parts.append("Job never started: approval or pin integrity check rejected.")
        if outcome is not None and outcome.error_message:
            parts.append(outcome.error_message)
        if parts:
            failure_analysis = "; ".join(parts)

    # ── Notes: artifacts, exit code, stdout/stderr summary ──
    notes_parts: list[str] = []
    if context.notes:
        notes_parts.append(context.notes)
    if outcome is not None and outcome.artifacts:
        notes_parts.append("artifacts=" + json.dumps(outcome.artifacts, sort_keys=True))
    if outcome is not None:
        exit_code = outcome.exit_code
        if exit_code is None:
            exit_code = outcome.resources.exit_code
        if exit_code is not None:
            notes_parts.append(f"exit_code={exit_code}")
        if outcome.stdout:
            # Store first 200 chars as a reference — ExperimentRecord has no
            # dedicated stdout field; full content should be preserved separately.
            preview = outcome.stdout[:200]
            notes_parts.append(f"stdout_preview={preview!r}")
        if outcome.stderr:
            preview = outcome.stderr[:200]
            notes_parts.append(f"stderr_preview={preview!r}")
    notes = "; ".join(notes_parts)

    return ExperimentRecord(
        exp_id=context.exp_id,
        status=exp_status,
        hypothesis=context.hypothesis,
        success_criteria=context.success_criteria,
        baseline_id=context.baseline_id,
        created_at=created_at,
        completed_at=completed_at,
        model=context.model if context.model else None,
        dataset_version=context.dataset_version,
        approval_ref=context.approval_ref,
        commit=context.commit,
        hardware=hardware,
        gpu_hours=gpu_hours,
        train_time=train_time,
        power=power,
        memory=memory,
        failure_analysis=failure_analysis,
        notes=notes,
    )
