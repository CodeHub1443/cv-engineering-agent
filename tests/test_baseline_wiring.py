"""
Tests for cv_agent.graph.experiment_wiring — JobResult → ExperimentRecord bridge.

Authorized by ADR-0013 §9 and ADR-0011 §8.

Coverage (numbered to match the task's required test list):
  1.  Successful JobResult → ExperimentRecord
  2.  baseline_id="SELF"
  3.  Failed job → correctly recorded experiment state
  4.  Cancelled job
  5.  Missing optional runtime/resource metadata
  6.  Artifact preservation
  7.  Exit-code preservation
  8.  No fabricated metrics (val_metrics/test_metrics/fps/latency absent)
  9.  Ledger persistence/retrieval
 10.  Approval integrity: no direct runtime invocation from wiring module
 11.  No direct runtime invocation
 12.  Idempotency/duplicate-record behavior (terminal record rejected on second write)
 13.  Non-terminal result raises ValueError
 14.  host_mismatch → "failed" ExperimentRecord
 15.  rejected → "cancelled" ExperimentRecord
 16.  Job without outcome (host_mismatch/rejected) → resource fields are None
 17.  Model candidate ID preserved from context
 18.  created_at from evidence.started_at
 19.  completed_at from evidence.completed_at
 20.  Fallback to injected _now_iso for missing timestamps
 21.  stdout/stderr summary stored in notes
 22.  Architecture boundary: wiring module doesn't import JobRuntime or JobExecutor
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cv_agent.execution.jobs.models import (
    JobOutcome,
    JobResourceMetadata,
    JobResult,
)
from cv_agent.execution.models import ExecutionError, ExecutionEvidence
from cv_agent.experiments.models import ExperimentRecord
from cv_agent.experiments.store import ExperimentLedgerError, open_ledger
from cv_agent.graph.experiment_wiring import ExperimentContext, job_result_to_experiment_record

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_STARTED_AT = "2026-09-28T10:00:00+00:00"
_COMPLETED_AT = "2026-09-28T10:05:00+00:00"
_FAKE_NOW = "2026-09-28T09:00:00+00:00"
_EXP_ID = "EXP-20260928-01"


def _evidence(
    *,
    started_at: str | None = _STARTED_AT,
    completed_at: str | None = _COMPLETED_AT,
) -> ExecutionEvidence:
    return ExecutionEvidence("binding-1", "runtime-1", started_at, completed_at)


def _resources(
    *,
    wall_time: float | None = 300.0,
    gpu_hours: float | None = 0.083,
    peak_vram_mb: float | None = 4096.0,
    peak_ram_mb: float | None = 8192.0,
    avg_power_watts: float | None = 150.0,
    exit_code: int | None = 0,
) -> JobResourceMetadata:
    return JobResourceMetadata(
        wall_time_seconds=wall_time,
        gpu_hours=gpu_hours,
        peak_vram_mb=peak_vram_mb,
        peak_ram_mb=peak_ram_mb,
        avg_power_watts=avg_power_watts,
        exit_code=exit_code,
    )


def _outcome(
    *,
    success: bool = True,
    exit_code: int | None = 0,
    stdout: str | None = None,
    stderr: str | None = None,
    artifacts: dict[str, str] | None = None,
    resources: JobResourceMetadata | None = None,
    error_message: str | None = None,
) -> JobOutcome:
    return JobOutcome(
        success=success,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        artifacts=artifacts or {},
        resources=resources or _resources(),
        error_message=error_message,
    )


def _completed_result(
    *,
    skill_id: str = "detect-and-track",
    job_id: str = "job-001",
    outcome: JobOutcome | None = None,
    evidence: ExecutionEvidence | None = None,
) -> JobResult:
    return JobResult(
        skill_id=skill_id,
        job_id=job_id,
        status="completed",
        evidence=evidence or _evidence(),
        outcome=outcome or _outcome(),
    )


def _context(
    *,
    exp_id: str = _EXP_ID,
    baseline_id: str = "SELF",
    hypothesis: str = "YOLO11n meets real-time detection on CCTV.",
    success_criteria: str = "Exit code 0 on reference sample.",
    model: str | None = "yolo11n",
    notes: str = "",
) -> ExperimentContext:
    return ExperimentContext(
        exp_id=exp_id,
        baseline_id=baseline_id,
        hypothesis=hypothesis,
        success_criteria=success_criteria,
        model=model,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 1. Successful JobResult → ExperimentRecord
# ---------------------------------------------------------------------------

class TestSuccessfulJobResult:
    def test_status_is_completed(self) -> None:
        rec = job_result_to_experiment_record(_completed_result(), context=_context())
        assert rec.status == "completed"

    def test_exp_id_preserved(self) -> None:
        rec = job_result_to_experiment_record(_completed_result(), context=_context())
        assert rec.exp_id == _EXP_ID

    def test_hypothesis_preserved(self) -> None:
        rec = job_result_to_experiment_record(_completed_result(), context=_context())
        assert rec.hypothesis == "YOLO11n meets real-time detection on CCTV."

    def test_success_criteria_preserved(self) -> None:
        rec = job_result_to_experiment_record(_completed_result(), context=_context())
        assert rec.success_criteria == "Exit code 0 on reference sample."

    def test_returns_experiment_record(self) -> None:
        rec = job_result_to_experiment_record(_completed_result(), context=_context())
        assert isinstance(rec, ExperimentRecord)

    def test_resource_fields_populated(self) -> None:
        result = _completed_result(outcome=_outcome(resources=_resources(
            wall_time=60.0, gpu_hours=0.016, avg_power_watts=120.0
        )))
        rec = job_result_to_experiment_record(result, context=_context())
        assert rec.train_time == 60.0
        assert rec.gpu_hours == 0.016
        assert rec.power == 120.0


# ---------------------------------------------------------------------------
# 2. baseline_id="SELF"
# ---------------------------------------------------------------------------

class TestBaselineId:
    def test_baseline_id_self_preserved(self) -> None:
        rec = job_result_to_experiment_record(
            _completed_result(), context=_context(baseline_id="SELF")
        )
        assert rec.baseline_id == "SELF"

    def test_baseline_id_exp_ref_preserved(self) -> None:
        ctx = _context(baseline_id="EXP-20260920-01")
        rec = job_result_to_experiment_record(_completed_result(), context=ctx)
        assert rec.baseline_id == "EXP-20260920-01"


# ---------------------------------------------------------------------------
# 3. Failed job
# ---------------------------------------------------------------------------

class TestFailedJob:
    def _make_failed(self, error_message: str = "non-zero exit") -> JobResult:
        return JobResult(
            skill_id="detect-and-track",
            job_id="job-002",
            status="failed",
            evidence=_evidence(),
            outcome=_outcome(
                success=False,
                exit_code=1,
                error_message=error_message,
                resources=_resources(exit_code=1),
            ),
            error=ExecutionError("runtime_error", "Process exited with code 1"),
        )

    def test_status_is_failed(self) -> None:
        rec = job_result_to_experiment_record(self._make_failed(), context=_context())
        assert rec.status == "failed"

    def test_failure_analysis_populated(self) -> None:
        rec = job_result_to_experiment_record(self._make_failed(), context=_context())
        assert rec.failure_analysis is not None
        assert "runtime_error" in rec.failure_analysis

    def test_failure_analysis_includes_error_message(self) -> None:
        rec = job_result_to_experiment_record(
            self._make_failed("GPU OOM"), context=_context()
        )
        assert rec.failure_analysis is not None
        assert "GPU OOM" in rec.failure_analysis

    def test_completed_at_set(self) -> None:
        rec = job_result_to_experiment_record(self._make_failed(), context=_context())
        assert rec.completed_at is not None


# ---------------------------------------------------------------------------
# 4. Cancelled job
# ---------------------------------------------------------------------------

class TestCancelledJob:
    def _make_cancelled(self) -> JobResult:
        return JobResult(
            skill_id="detect-and-track",
            job_id="job-003",
            status="cancelled",
            evidence=_evidence(),
            outcome=_outcome(
                success=False,
                exit_code=None,
                error_message="cancelled",
                resources=JobResourceMetadata(),
            ),
            error=ExecutionError("cancelled", "Job was cancelled by the user."),
        )

    def test_status_is_cancelled(self) -> None:
        rec = job_result_to_experiment_record(self._make_cancelled(), context=_context())
        assert rec.status == "cancelled"

    def test_failure_analysis_mentions_cancellation(self) -> None:
        rec = job_result_to_experiment_record(self._make_cancelled(), context=_context())
        assert rec.failure_analysis is not None
        assert "cancel" in rec.failure_analysis.lower()

    def test_completed_at_set(self) -> None:
        rec = job_result_to_experiment_record(self._make_cancelled(), context=_context())
        assert rec.completed_at is not None


# ---------------------------------------------------------------------------
# 5. Missing optional resource metadata
# ---------------------------------------------------------------------------

class TestMissingResourceMetadata:
    def test_all_resources_none_produces_none_fields(self) -> None:
        result = _completed_result(
            outcome=_outcome(resources=JobResourceMetadata())
        )
        rec = job_result_to_experiment_record(result, context=_context())
        assert rec.gpu_hours is None
        assert rec.train_time is None
        assert rec.power is None
        assert rec.memory is None

    def test_partial_vram_only(self) -> None:
        result = _completed_result(
            outcome=_outcome(resources=JobResourceMetadata(peak_vram_mb=2048.0))
        )
        rec = job_result_to_experiment_record(result, context=_context())
        assert rec.memory is not None
        assert rec.memory.vram == 2048.0
        assert rec.memory.ram == 0.0

    def test_partial_ram_only(self) -> None:
        result = _completed_result(
            outcome=_outcome(resources=JobResourceMetadata(peak_ram_mb=4096.0))
        )
        rec = job_result_to_experiment_record(result, context=_context())
        assert rec.memory is not None
        assert rec.memory.ram == 4096.0
        assert rec.memory.vram == 0.0

    def test_no_outcome_at_all_produces_none_resources(self) -> None:
        result = JobResult(
            skill_id="s",
            job_id=None,
            status="host_mismatch",
            evidence=_evidence(started_at=None, completed_at=None),
            error=ExecutionError("host_mismatch", "Not Linux"),
        )
        rec = job_result_to_experiment_record(
            result, context=_context(), _now_iso=_FAKE_NOW
        )
        assert rec.gpu_hours is None
        assert rec.train_time is None
        assert rec.memory is None


# ---------------------------------------------------------------------------
# 6. Artifact preservation
# ---------------------------------------------------------------------------

class TestArtifactPreservation:
    def test_artifacts_serialised_in_notes(self) -> None:
        artifacts = {
            "pipeline-config": "/tmp/pipeline.cfg",
            "inference-log": "/tmp/run.log",
        }
        result = _completed_result(outcome=_outcome(artifacts=artifacts))
        rec = job_result_to_experiment_record(result, context=_context())
        assert "artifacts=" in rec.notes
        assert "pipeline-config" in rec.notes
        assert "/tmp/pipeline.cfg" in rec.notes

    def test_empty_artifacts_not_in_notes(self) -> None:
        result = _completed_result(outcome=_outcome(artifacts={}))
        rec = job_result_to_experiment_record(result, context=_context())
        assert "artifacts=" not in rec.notes

    def test_artifact_paths_are_not_modified(self) -> None:
        """Artifact paths stored exactly as given — no normalization."""
        artifacts = {"report": "/abs/path/to/report.json"}
        result = _completed_result(outcome=_outcome(artifacts=artifacts))
        rec = job_result_to_experiment_record(result, context=_context())
        assert "/abs/path/to/report.json" in rec.notes


# ---------------------------------------------------------------------------
# 7. Exit-code preservation
# ---------------------------------------------------------------------------

class TestExitCodePreservation:
    def test_exit_code_from_outcome_in_notes(self) -> None:
        result = _completed_result(
            outcome=_outcome(exit_code=0, resources=_resources(exit_code=0))
        )
        rec = job_result_to_experiment_record(result, context=_context())
        assert "exit_code=0" in rec.notes

    def test_nonzero_exit_code_preserved(self) -> None:
        result = JobResult(
            skill_id="s",
            job_id="j",
            status="failed",
            evidence=_evidence(),
            outcome=_outcome(
                success=False,
                exit_code=137,
                resources=_resources(exit_code=137),
            ),
            error=ExecutionError("runtime_error", "killed"),
        )
        rec = job_result_to_experiment_record(result, context=_context())
        assert "exit_code=137" in rec.notes

    def test_exit_code_from_resources_when_outcome_code_none(self) -> None:
        result = _completed_result(
            outcome=_outcome(
                exit_code=None,
                resources=JobResourceMetadata(exit_code=0),
            )
        )
        rec = job_result_to_experiment_record(result, context=_context())
        assert "exit_code=0" in rec.notes


# ---------------------------------------------------------------------------
# 8. No fabricated metrics
# ---------------------------------------------------------------------------

class TestNoFabricatedMetrics:
    def test_val_metrics_absent_when_not_in_context(self) -> None:
        rec = job_result_to_experiment_record(_completed_result(), context=_context())
        assert rec.val_metrics is None

    def test_test_metrics_absent(self) -> None:
        rec = job_result_to_experiment_record(_completed_result(), context=_context())
        assert rec.test_metrics is None

    def test_fps_absent(self) -> None:
        rec = job_result_to_experiment_record(_completed_result(), context=_context())
        assert rec.fps is None

    def test_latency_absent(self) -> None:
        rec = job_result_to_experiment_record(_completed_result(), context=_context())
        assert rec.latency is None

    def test_params_absent(self) -> None:
        rec = job_result_to_experiment_record(_completed_result(), context=_context())
        assert rec.params is None

    def test_flops_absent(self) -> None:
        rec = job_result_to_experiment_record(_completed_result(), context=_context())
        assert rec.flops is None


# ---------------------------------------------------------------------------
# 9. Ledger persistence / retrieval
# ---------------------------------------------------------------------------

class TestLedgerPersistence:
    def test_record_can_be_written_and_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = open_ledger(db_path=Path(tmpdir) / "exp.sqlite")
            rec = job_result_to_experiment_record(
                _completed_result(), context=_context()
            )
            ledger.record_experiment(rec)
            retrieved = ledger.get_experiment(_EXP_ID)
            assert retrieved is not None
            assert retrieved.exp_id == rec.exp_id
            assert retrieved.status == rec.status

    def test_written_record_appears_in_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = open_ledger(db_path=Path(tmpdir) / "exp.sqlite")
            rec = job_result_to_experiment_record(
                _completed_result(), context=_context()
            )
            ledger.record_experiment(rec)
            records = ledger.list_experiments()
            assert len(records) == 1
            assert records[0].exp_id == _EXP_ID

    def test_all_populated_fields_survive_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = open_ledger(db_path=Path(tmpdir) / "exp.sqlite")
            ctx = ExperimentContext(
                exp_id=_EXP_ID,
                baseline_id="SELF",
                hypothesis="Baseline person detection.",
                success_criteria="Exit 0.",
                model="yolo11n",
                approval_ref="approved",
                hardware_training="NVIDIA A100",
                hardware_target="NVIDIA Jetson Orin",
            )
            rec = job_result_to_experiment_record(_completed_result(), context=ctx)
            ledger.record_experiment(rec)
            retrieved = ledger.get_experiment(_EXP_ID)
            assert retrieved is not None
            assert retrieved.model == "yolo11n"
            assert retrieved.approval_ref == "approved"
            assert retrieved.hardware is not None
            assert retrieved.hardware.training == "NVIDIA A100"
            assert retrieved.hardware.target == "NVIDIA Jetson Orin"


# ---------------------------------------------------------------------------
# 10/11. Approval integrity & no direct runtime invocation
# ---------------------------------------------------------------------------

class TestArchitectureBoundary:
    def test_wiring_module_does_not_import_job_executor(self) -> None:
        """experiment_wiring must not import JobExecutor — it's not in the execution chain."""
        import ast
        import inspect
        import cv_agent.graph.experiment_wiring as wiring_mod
        source = inspect.getsource(wiring_mod)
        tree = ast.parse(source)
        imported_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.names:
                    imported_names.extend(alias.name or "" for alias in node.names)
            elif isinstance(node, ast.Import):
                imported_names.extend(alias.name or "" for alias in node.names)
        assert "JobExecutor" not in imported_names
        assert "JobRuntime" not in imported_names

    def test_wiring_module_does_not_import_host_verifier(self) -> None:
        """experiment_wiring must not invoke host verification — that's JobExecutor's job."""
        import ast
        import inspect
        import cv_agent.graph.experiment_wiring as wiring_mod
        source = inspect.getsource(wiring_mod)
        tree = ast.parse(source)
        imported_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.names:
                    imported_names.extend(alias.name or "" for alias in node.names)
        assert "HostVerifier" not in imported_names

    def test_wiring_function_does_not_accept_ledger(self) -> None:
        """job_result_to_experiment_record does not write to ledger — it returns a record."""
        import inspect
        sig = inspect.signature(job_result_to_experiment_record)
        assert "ledger" not in sig.parameters

    def test_approval_check_not_bypassed(self) -> None:
        """
        The wiring function accepts a JobResult — which can only exist if JobExecutor
        ran, which requires approval. Structural proof: no 'approved' param in signature.
        """
        import inspect
        sig = inspect.signature(job_result_to_experiment_record)
        assert "approved" not in sig.parameters
        assert "bypass" not in sig.parameters


# ---------------------------------------------------------------------------
# 12. Idempotency / duplicate-record behavior
# ---------------------------------------------------------------------------

class TestDuplicateRecord:
    def test_writing_terminal_record_twice_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = open_ledger(db_path=Path(tmpdir) / "exp.sqlite")
            rec = job_result_to_experiment_record(
                _completed_result(), context=_context()
            )
            ledger.record_experiment(rec)
            with pytest.raises(ExperimentLedgerError):
                ledger.record_experiment(rec)

    def test_writing_terminal_record_twice_leaves_original_intact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = open_ledger(db_path=Path(tmpdir) / "exp.sqlite")
            rec = job_result_to_experiment_record(
                _completed_result(), context=_context()
            )
            ledger.record_experiment(rec)
            try:
                ledger.record_experiment(rec)
            except ExperimentLedgerError:
                pass
            retrieved = ledger.get_experiment(_EXP_ID)
            assert retrieved is not None
            assert retrieved.status == "completed"


# ---------------------------------------------------------------------------
# 13. Non-terminal result raises ValueError
# ---------------------------------------------------------------------------

class TestNonTerminalRejected:
    @pytest.mark.parametrize("status", ["started", "running", "not_submitted"])
    def test_non_terminal_status_raises(self, status: str) -> None:
        result = JobResult(
            skill_id="s",
            job_id="j",
            status=status,  # type: ignore[arg-type]
            evidence=_evidence(completed_at=None),
        )
        with pytest.raises(ValueError, match="terminal"):
            job_result_to_experiment_record(result, context=_context())


# ---------------------------------------------------------------------------
# 14. host_mismatch → "failed"
# ---------------------------------------------------------------------------

class TestHostMismatch:
    def _make_host_mismatch(self) -> JobResult:
        return JobResult(
            skill_id="s",
            job_id=None,
            status="host_mismatch",
            evidence=_evidence(started_at=None, completed_at=None),
            error=ExecutionError("host_mismatch", "Required Linux; got darwin"),
        )

    def test_status_is_failed(self) -> None:
        rec = job_result_to_experiment_record(
            self._make_host_mismatch(), context=_context(), _now_iso=_FAKE_NOW
        )
        assert rec.status == "failed"

    def test_failure_analysis_mentions_host(self) -> None:
        rec = job_result_to_experiment_record(
            self._make_host_mismatch(), context=_context(), _now_iso=_FAKE_NOW
        )
        assert rec.failure_analysis is not None
        assert "host" in rec.failure_analysis.lower()

    def test_completed_at_falls_back_to_now(self) -> None:
        rec = job_result_to_experiment_record(
            self._make_host_mismatch(), context=_context(), _now_iso=_FAKE_NOW
        )
        assert rec.completed_at == _FAKE_NOW


# ---------------------------------------------------------------------------
# 15. rejected → "cancelled"
# ---------------------------------------------------------------------------

class TestRejected:
    def _make_rejected(self) -> JobResult:
        return JobResult(
            skill_id="s",
            job_id=None,
            status="rejected",
            evidence=_evidence(started_at=None, completed_at=None),
            error=ExecutionError("approval_denied", "User denied."),
        )

    def test_status_is_cancelled(self) -> None:
        rec = job_result_to_experiment_record(
            self._make_rejected(), context=_context(), _now_iso=_FAKE_NOW
        )
        assert rec.status == "cancelled"

    def test_failure_analysis_mentions_rejection(self) -> None:
        rec = job_result_to_experiment_record(
            self._make_rejected(), context=_context(), _now_iso=_FAKE_NOW
        )
        assert rec.failure_analysis is not None
        assert "rejected" in rec.failure_analysis.lower() or "approval" in rec.failure_analysis.lower()


# ---------------------------------------------------------------------------
# 16. Jobs without outcome
# ---------------------------------------------------------------------------

class TestJobsWithoutOutcome:
    def test_host_mismatch_has_no_resource_fields(self) -> None:
        result = JobResult(
            skill_id="s",
            job_id=None,
            status="host_mismatch",
            evidence=_evidence(started_at=None, completed_at=None),
            error=ExecutionError("host_mismatch", "No GPU"),
        )
        rec = job_result_to_experiment_record(
            result, context=_context(), _now_iso=_FAKE_NOW
        )
        assert rec.train_time is None
        assert rec.gpu_hours is None
        assert rec.power is None
        assert rec.memory is None

    def test_rejected_has_no_resource_fields(self) -> None:
        result = JobResult(
            skill_id="s",
            job_id=None,
            status="rejected",
            evidence=_evidence(started_at=None, completed_at=None),
            error=ExecutionError("binding_mismatch", "Pin stale"),
        )
        rec = job_result_to_experiment_record(
            result, context=_context(), _now_iso=_FAKE_NOW
        )
        assert rec.train_time is None
        assert rec.gpu_hours is None


# ---------------------------------------------------------------------------
# 17. Model candidate ID preserved from context
# ---------------------------------------------------------------------------

class TestModelCandidateId:
    def test_model_candidate_id_in_record(self) -> None:
        ctx = _context(model="yolo11n")
        rec = job_result_to_experiment_record(_completed_result(), context=ctx)
        assert rec.model == "yolo11n"

    def test_rtdetr_candidate_id_preserved(self) -> None:
        ctx = _context(model="rtdetr-r50")
        rec = job_result_to_experiment_record(_completed_result(), context=ctx)
        assert rec.model == "rtdetr-r50"

    def test_no_model_produces_none(self) -> None:
        ctx = _context(model=None)
        rec = job_result_to_experiment_record(_completed_result(), context=ctx)
        assert rec.model is None


# ---------------------------------------------------------------------------
# 18. created_at from evidence.started_at
# ---------------------------------------------------------------------------

class TestTimestamps:
    def test_created_at_from_evidence_started_at(self) -> None:
        result = _completed_result(evidence=_evidence(started_at=_STARTED_AT))
        rec = job_result_to_experiment_record(result, context=_context())
        assert rec.created_at == _STARTED_AT

    def test_completed_at_from_evidence_completed_at(self) -> None:
        result = _completed_result(evidence=_evidence(completed_at=_COMPLETED_AT))
        rec = job_result_to_experiment_record(result, context=_context())
        assert rec.completed_at == _COMPLETED_AT

    def test_fallback_to_now_when_started_at_missing(self) -> None:
        result = _completed_result(
            evidence=_evidence(started_at=None, completed_at=None)
        )
        rec = job_result_to_experiment_record(
            result, context=_context(), _now_iso=_FAKE_NOW
        )
        assert rec.created_at == _FAKE_NOW

    def test_fallback_to_now_when_completed_at_missing(self) -> None:
        # _now_iso must be after started_at to satisfy completed_at >= created_at
        late_now = "2026-09-28T11:00:00+00:00"
        result = _completed_result(
            evidence=_evidence(completed_at=None)
        )
        rec = job_result_to_experiment_record(
            result, context=_context(), _now_iso=late_now
        )
        assert rec.completed_at == late_now


# ---------------------------------------------------------------------------
# 21. stdout/stderr summary in notes
# ---------------------------------------------------------------------------

class TestStdoutStderrSummary:
    def test_stdout_preview_in_notes(self) -> None:
        result = _completed_result(
            outcome=_outcome(stdout="Detection results: 42 persons found.")
        )
        rec = job_result_to_experiment_record(result, context=_context())
        assert "stdout_preview" in rec.notes
        assert "Detection results" in rec.notes

    def test_stderr_preview_in_notes_for_failed(self) -> None:
        result = JobResult(
            skill_id="s",
            job_id="j",
            status="failed",
            evidence=_evidence(),
            outcome=_outcome(
                success=False,
                exit_code=1,
                stderr="CUDA error: out of memory",
                resources=_resources(exit_code=1),
            ),
            error=ExecutionError("runtime_error", "non-zero exit"),
        )
        rec = job_result_to_experiment_record(result, context=_context())
        assert "stderr_preview" in rec.notes
        assert "CUDA error" in rec.notes

    def test_no_stdout_no_preview_in_notes(self) -> None:
        result = _completed_result(outcome=_outcome(stdout=None, stderr=None))
        rec = job_result_to_experiment_record(result, context=_context())
        assert "stdout_preview" not in rec.notes
        assert "stderr_preview" not in rec.notes

    def test_long_stdout_truncated(self) -> None:
        long_output = "x" * 500
        result = _completed_result(outcome=_outcome(stdout=long_output))
        rec = job_result_to_experiment_record(result, context=_context())
        assert "stdout_preview" in rec.notes
        # Notes should not contain the full 500-char output
        assert len(rec.notes) < len(long_output) + 200


# ---------------------------------------------------------------------------
# Hardware context
# ---------------------------------------------------------------------------

class TestHardwareContext:
    def test_hardware_populated_when_both_provided(self) -> None:
        ctx = ExperimentContext(
            exp_id=_EXP_ID,
            baseline_id="SELF",
            hypothesis="h",
            success_criteria="s",
            hardware_training="NVIDIA A100",
            hardware_target="NVIDIA Jetson Orin",
        )
        rec = job_result_to_experiment_record(_completed_result(), context=ctx)
        assert rec.hardware is not None
        assert rec.hardware.training == "NVIDIA A100"
        assert rec.hardware.target == "NVIDIA Jetson Orin"

    def test_hardware_none_when_only_training_given(self) -> None:
        ctx = ExperimentContext(
            exp_id=_EXP_ID,
            baseline_id="SELF",
            hypothesis="h",
            success_criteria="s",
            hardware_training="NVIDIA A100",
            hardware_target=None,
        )
        rec = job_result_to_experiment_record(_completed_result(), context=ctx)
        assert rec.hardware is None

    def test_hardware_none_when_neither_given(self) -> None:
        rec = job_result_to_experiment_record(
            _completed_result(), context=_context()
        )
        assert rec.hardware is None
