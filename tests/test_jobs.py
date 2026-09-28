"""
Tests for cv_agent.execution.jobs and cv_agent.execution.host.

All tests use fake runtimes and verifiers constructed in this file.
No NVIDIA hardware, no real subprocesses, no real CV workloads required.

Coverage:
  - LinuxNvidiaHostVerifier with injected HostProfile (deterministic)
  - JobExecutor pre-flight check order (all 9 failure paths + success)
  - Approval-pin mismatch (stale pin, malformed pin)
  - Host mismatch (OS mismatch, GPU vendor mismatch)
  - E1 rule: absent pin with approval_required
  - Terminal/non-terminal lifecycle via FakeJobRuntime
  - cancel() from started state
  - cancel() from running state
  - collect()-after-terminal (idempotent, non-blocking)
  - collect()-is-not-called-on-non-terminal (enforced by test design)
  - runtime_id collision guard at JobExecutor construction
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pytest

from cv_agent.execution.binding import ExecutionBinding, ExecutionBindingRegistry
from cv_agent.execution.host import (
    HostProfile,
    HostRequirement,
    LinuxNvidiaHostVerifier,
)
from cv_agent.execution.jobs.executor import JobExecutor
from cv_agent.execution.jobs.models import JobHandle, JobOutcome, JobResourceMetadata
from cv_agent.execution.models import RuntimeOutcome, SkillExecutionRequest
from cv_agent.skills.models import Skill


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _skill(skill_id: str = "job-skill") -> Skill:
    return Skill(
        skill_id=skill_id,
        name=skill_id,
        description="A fake job test skill.",
        source="fixture",
        location=f"/fixtures/{skill_id}/SKILL.md",
    )


def _binding(
    skill_id: str = "job-skill",
    runtime_id: str = "job-runtime",
    approval_policy: str = "allowed",
    verified: bool = True,
) -> ExecutionBinding:
    return ExecutionBinding(
        skill_id=skill_id,
        binding_id=f"b-{skill_id}",
        runtime_id=runtime_id,
        approval_policy=approval_policy,  # type: ignore[arg-type]
        verified=verified,
    )


def _linux_nvidia_profile() -> HostProfile:
    return HostProfile(
        os="linux",
        gpu_available=True,
        gpu_vendor="nvidia",
        driver_version="535.183.01",
    )


def _passing_verifier() -> LinuxNvidiaHostVerifier:
    return LinuxNvidiaHostVerifier(profile=_linux_nvidia_profile())


def _linux_nvidia_req() -> HostRequirement:
    return HostRequirement(os="linux", gpu_vendor="nvidia")


@dataclass
class FakeJobRuntime:
    """
    Configurable fake JobRuntime for unit tests.

    poll_sequence: list of statuses returned by successive poll() calls.
    After exhaustion, always returns the last element.
    start_raises: if set, start() raises this exception.
    """

    runtime_id: str = "job-runtime"
    poll_sequence: list[str] = field(default_factory=lambda: ["running", "completed"])
    start_raises: Exception | None = None
    cancelled: bool = False
    _start_calls: list[tuple[str, dict]] = field(default_factory=list, repr=False)
    _poll_index: int = field(default=0, init=False, repr=False)
    _outcome: JobOutcome | None = field(default=None, init=False, repr=False)
    _cancelled: bool = field(default=False, init=False, repr=False)

    def start(self, skill: Skill, request: SkillExecutionRequest) -> JobHandle:
        self._start_calls.append((skill.skill_id, dict(request.inputs)))
        if self.start_raises is not None:
            raise self.start_raises
        return JobHandle(
            job_id=f"job-{skill.skill_id}-001",
            runtime_id=self.runtime_id,
            started_at="2026-09-28T00:00:00+00:00",
        )

    def poll(
        self, handle: JobHandle
    ) -> Literal["running", "completed", "failed", "cancelled"]:
        seq = self.poll_sequence
        idx = min(self._poll_index, len(seq) - 1)
        result = seq[idx]
        self._poll_index += 1
        return result  # type: ignore[return-value]

    def cancel(self, handle: JobHandle) -> None:
        self._cancelled = True
        # Replace remaining poll sequence to return "cancelled" next.
        self._poll_index = 0
        self.poll_sequence = ["cancelled"]

    def collect(self, handle: JobHandle) -> JobOutcome:
        if self._cancelled:
            return JobOutcome(
                success=False,
                exit_code=None,
                stdout=None,
                stderr=None,
                error_message="cancelled",
            )
        return JobOutcome(
            success=True,
            exit_code=0,
            stdout="done",
            stderr="",
            artifacts={"model": "/tmp/model.pt"},
            resources=JobResourceMetadata(wall_time_seconds=1.5),
        )


def _registry_with_binding(binding: ExecutionBinding) -> ExecutionBindingRegistry:
    reg = ExecutionBindingRegistry()
    reg.register_binding(binding)
    return reg


def _executor(
    binding: ExecutionBinding,
    runtime: FakeJobRuntime | None = None,
    verifier: LinuxNvidiaHostVerifier | None = None,
) -> tuple[JobExecutor, FakeJobRuntime | None]:
    reg = _registry_with_binding(binding)
    rt = runtime or FakeJobRuntime()
    job_runtimes: dict[str, FakeJobRuntime] = {}
    if runtime is not None or True:
        # Always register runtime unless explicitly excluded
        job_runtimes = {rt.runtime_id: rt} if runtime is not None else {}
        if runtime is None:
            rt = None  # type: ignore[assignment]
    v = verifier or _passing_verifier()
    exec_ = JobExecutor(
        registry=reg,
        job_runtimes=job_runtimes,
        host_verifier=v,
    )
    return exec_, rt


def _full_executor(
    binding: ExecutionBinding | None = None,
    runtime: FakeJobRuntime | None = None,
    verifier: LinuxNvidiaHostVerifier | None = None,
) -> tuple[JobExecutor, FakeJobRuntime]:
    b = binding or _binding()
    rt = runtime or FakeJobRuntime()
    reg = _registry_with_binding(b)
    v = verifier or _passing_verifier()
    exec_ = JobExecutor(
        registry=reg,
        job_runtimes={rt.runtime_id: rt},
        host_verifier=v,
    )
    return exec_, rt


# ---------------------------------------------------------------------------
# LinuxNvidiaHostVerifier
# ---------------------------------------------------------------------------

class TestLinuxNvidiaHostVerifier:
    def test_passes_with_matching_linux_nvidia_profile(self) -> None:
        verifier = LinuxNvidiaHostVerifier(profile=_linux_nvidia_profile())
        ok, reason = verifier.verify(HostRequirement(os="linux", gpu_vendor="nvidia"))
        assert ok is True
        assert reason == ""

    def test_fails_on_os_mismatch(self) -> None:
        profile = HostProfile(os="darwin", gpu_available=True, gpu_vendor="nvidia", driver_version=None)
        verifier = LinuxNvidiaHostVerifier(profile=profile)
        ok, reason = verifier.verify(HostRequirement(os="linux", gpu_vendor="nvidia"))
        assert ok is False
        assert "darwin" in reason
        assert "linux" in reason

    def test_fails_on_gpu_vendor_mismatch(self) -> None:
        profile = HostProfile(os="linux", gpu_available=True, gpu_vendor="amd", driver_version=None)
        verifier = LinuxNvidiaHostVerifier(profile=profile)
        ok, reason = verifier.verify(HostRequirement(os="linux", gpu_vendor="nvidia"))
        assert ok is False
        assert "nvidia" in reason

    def test_fails_when_no_gpu_but_gpu_vendor_required(self) -> None:
        profile = HostProfile(os="linux", gpu_available=False, gpu_vendor=None, driver_version=None)
        verifier = LinuxNvidiaHostVerifier(profile=profile)
        ok, reason = verifier.verify(HostRequirement(os="linux", gpu_vendor="nvidia"))
        assert ok is False

    def test_passes_when_no_gpu_vendor_required(self) -> None:
        profile = HostProfile(os="linux", gpu_available=False, gpu_vendor=None, driver_version=None)
        verifier = LinuxNvidiaHostVerifier(profile=profile)
        ok, reason = verifier.verify(HostRequirement(os="linux", gpu_vendor=None))
        assert ok is True
        assert reason == ""

    def test_os_comparison_is_case_insensitive(self) -> None:
        profile = HostProfile(os="linux", gpu_available=True, gpu_vendor="nvidia", driver_version=None)
        verifier = LinuxNvidiaHostVerifier(profile=profile)
        ok, _ = verifier.verify(HostRequirement(os="Linux", gpu_vendor="nvidia"))
        assert ok is True

    def test_fails_when_min_vram_required_but_no_gpu(self) -> None:
        profile = HostProfile(os="linux", gpu_available=False, gpu_vendor=None, driver_version=None)
        verifier = LinuxNvidiaHostVerifier(profile=profile)
        ok, reason = verifier.verify(HostRequirement(os="linux", min_vram_mb=8192))
        assert ok is False

    def test_verify_never_raises(self) -> None:
        # Simulate a broken profile factory.
        class BrokenVerifier(LinuxNvidiaHostVerifier):
            def _get_profile(self) -> HostProfile:
                raise RuntimeError("detection crashed")

        verifier = BrokenVerifier()
        ok, reason = verifier.verify(HostRequirement(os="linux"))
        assert ok is False
        assert "detection" in reason.lower() or "crashed" in reason.lower()


# ---------------------------------------------------------------------------
# JobExecutor: pre-flight failures
# ---------------------------------------------------------------------------

class TestJobExecutorPreFlight:
    def test_no_binding_returns_not_submitted(self) -> None:
        reg = ExecutionBindingRegistry()
        exec_ = JobExecutor(
            registry=reg,
            job_runtimes={"job-runtime": FakeJobRuntime()},
            host_verifier=_passing_verifier(),
        )
        handle, result = exec_.start_job(_skill(), SkillExecutionRequest(), _linux_nvidia_req())
        assert handle is None
        assert result.status == "not_submitted"
        assert result.error is not None
        assert result.error.category == "no_binding"

    def test_unverified_binding_returns_not_submitted(self) -> None:
        exec_, _ = _full_executor(binding=_binding(verified=False))
        handle, result = exec_.start_job(_skill(), SkillExecutionRequest(), _linux_nvidia_req())
        assert handle is None
        assert result.status == "not_submitted"
        assert result.error is not None
        assert result.error.category == "binding_not_verified"

    def test_policy_rejected_returns_rejected(self) -> None:
        exec_, _ = _full_executor(binding=_binding(approval_policy="rejected"))
        handle, result = exec_.start_job(_skill(), SkillExecutionRequest(), _linux_nvidia_req())
        assert handle is None
        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.category == "approval_denied"

    def test_e1_absent_pin_with_approval_required_returns_rejected(self) -> None:
        exec_, _ = _full_executor(binding=_binding(approval_policy="approval_required"))
        # No pin supplied, approved=False — E1 fires on missing pin alone.
        handle, result = exec_.start_job(
            _skill(),
            SkillExecutionRequest(approved=False, expected_binding_pin=None),
            _linux_nvidia_req(),
        )
        assert handle is None
        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.category == "approval_denied"
        assert "expected_binding_pin" in result.error.message

    def test_e1_fires_even_when_approved_true_but_no_pin(self) -> None:
        """approved=True without a pin must still be refused (E1)."""
        exec_, _ = _full_executor(binding=_binding(approval_policy="approval_required"))
        handle, result = exec_.start_job(
            _skill(),
            SkillExecutionRequest(approved=True, expected_binding_pin=None),
            _linux_nvidia_req(),
        )
        assert handle is None
        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.category == "approval_denied"

    def test_stale_pin_returns_rejected_binding_mismatch(self) -> None:
        reg = ExecutionBindingRegistry()
        binding = _binding()
        reg.register_binding(binding)
        rt = FakeJobRuntime()
        exec_ = JobExecutor(
            registry=reg,
            job_runtimes={rt.runtime_id: rt},
            host_verifier=_passing_verifier(),
        )
        # Capture a valid pin.
        live_pin = reg.pin("job-skill")
        assert live_pin is not None

        # Tamper with the pin to simulate a changed binding.
        stale_pin = {
            "binding": {**live_pin["binding"], "approval_policy": "rejected"},
            "runtime_generation": live_pin["runtime_generation"],
        }
        handle, result = exec_.start_job(
            _skill(),
            SkillExecutionRequest(expected_binding_pin=stale_pin),
            _linux_nvidia_req(),
        )
        assert handle is None
        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.category == "binding_mismatch"
        assert "binding.approval_policy" in result.error.message

    def test_malformed_pin_returns_rejected_binding_mismatch(self) -> None:
        exec_, _ = _full_executor()
        handle, result = exec_.start_job(
            _skill(),
            SkillExecutionRequest(expected_binding_pin={"not": "a valid pin"}),
            _linux_nvidia_req(),
        )
        assert handle is None
        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.category == "binding_mismatch"

    def test_approval_required_not_approved_returns_rejected(self) -> None:
        reg = ExecutionBindingRegistry()
        binding = _binding(approval_policy="approval_required")
        reg.register_binding(binding)
        rt = FakeJobRuntime()
        exec_ = JobExecutor(
            registry=reg,
            job_runtimes={rt.runtime_id: rt},
            host_verifier=_passing_verifier(),
        )
        live_pin = reg.pin("job-skill")
        handle, result = exec_.start_job(
            _skill(),
            SkillExecutionRequest(approved=False, expected_binding_pin=live_pin),
            _linux_nvidia_req(),
        )
        assert handle is None
        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.category == "approval_denied"

    def test_no_job_runtime_registered_returns_not_submitted(self) -> None:
        reg = _registry_with_binding(_binding())
        exec_ = JobExecutor(
            registry=reg,
            job_runtimes={},  # no runtime
            host_verifier=_passing_verifier(),
        )
        handle, result = exec_.start_job(_skill(), SkillExecutionRequest(), _linux_nvidia_req())
        assert handle is None
        assert result.status == "not_submitted"
        assert result.error is not None
        assert result.error.category == "no_binding"

    def test_host_mismatch_returns_host_mismatch(self) -> None:
        wrong_os_profile = HostProfile(
            os="darwin", gpu_available=True, gpu_vendor="nvidia", driver_version=None
        )
        exec_, _ = _full_executor(verifier=LinuxNvidiaHostVerifier(profile=wrong_os_profile))
        handle, result = exec_.start_job(_skill(), SkillExecutionRequest(), _linux_nvidia_req())
        assert handle is None
        assert result.status == "host_mismatch"
        assert result.error is not None
        assert result.error.category == "host_mismatch"
        assert "darwin" in result.error.message

    def test_start_raises_returns_failed(self) -> None:
        failing_rt = FakeJobRuntime(start_raises=RuntimeError("GPU OOM"))
        exec_, _ = _full_executor(runtime=failing_rt)
        handle, result = exec_.start_job(_skill(), SkillExecutionRequest(), _linux_nvidia_req())
        assert handle is None
        assert result.status == "failed"
        assert result.error is not None
        assert result.error.category == "runtime_error"
        assert "GPU OOM" in result.error.message


# ---------------------------------------------------------------------------
# JobExecutor: successful start
# ---------------------------------------------------------------------------

class TestJobExecutorSuccess:
    def test_successful_start_returns_handle_and_started_status(self) -> None:
        exec_, rt = _full_executor()
        handle, result = exec_.start_job(_skill(), SkillExecutionRequest(), _linux_nvidia_req())
        assert handle is not None
        assert result.status == "started"
        assert result.job_id == handle.job_id
        assert result.ok is False  # started is not "completed"
        assert result.terminal is False
        assert result.error is None
        assert result.outcome is None
        assert result.evidence.binding_id is not None
        assert result.evidence.runtime_id == "job-runtime"
        assert result.evidence.started_at is not None
        assert result.evidence.completed_at is None  # job still running

    def test_approved_with_pin_starts_successfully(self) -> None:
        reg = ExecutionBindingRegistry()
        binding = _binding(approval_policy="approval_required")
        reg.register_binding(binding)
        rt = FakeJobRuntime()
        exec_ = JobExecutor(
            registry=reg,
            job_runtimes={rt.runtime_id: rt},
            host_verifier=_passing_verifier(),
        )
        live_pin = reg.pin("job-skill")
        handle, result = exec_.start_job(
            _skill(),
            SkillExecutionRequest(approved=True, expected_binding_pin=live_pin),
            _linux_nvidia_req(),
        )
        assert handle is not None
        assert result.status == "started"

    def test_can_start_inspect_only(self) -> None:
        exec_, _ = _full_executor()
        assert exec_.can_start("job-skill") is True
        assert exec_.can_start("nonexistent") is False

    def test_start_job_records_skill_id_in_result(self) -> None:
        exec_, _ = _full_executor()
        handle, result = exec_.start_job(
            _skill("custom-job"), SkillExecutionRequest(), _linux_nvidia_req()
        )
        # skill_id in result, but the binding was registered for "job-skill"
        # so this should be not_submitted (no binding for custom-job)
        assert result.skill_id == "custom-job"
        assert result.status == "not_submitted"


# ---------------------------------------------------------------------------
# JobExecutor: poll lifecycle
# ---------------------------------------------------------------------------

class TestJobExecutorPoll:
    def test_poll_returns_running_while_alive(self) -> None:
        rt = FakeJobRuntime(poll_sequence=["running", "running", "completed"])
        exec_, _ = _full_executor(runtime=rt)
        handle, _ = exec_.start_job(_skill(), SkillExecutionRequest(), _linux_nvidia_req())
        assert handle is not None
        assert exec_.poll_job(handle) == "running"
        assert exec_.poll_job(handle) == "running"
        assert exec_.poll_job(handle) == "completed"

    def test_poll_returns_failed(self) -> None:
        rt = FakeJobRuntime(poll_sequence=["running", "failed"])
        exec_, _ = _full_executor(runtime=rt)
        handle, _ = exec_.start_job(_skill(), SkillExecutionRequest(), _linux_nvidia_req())
        assert handle is not None
        exec_.poll_job(handle)  # running
        assert exec_.poll_job(handle) == "failed"

    def test_poll_unknown_runtime_raises(self) -> None:
        exec_, _ = _full_executor()
        bad_handle = JobHandle(
            job_id="x", runtime_id="nonexistent-runtime", started_at="2026-01-01T00:00:00+00:00"
        )
        with pytest.raises(RuntimeError, match="nonexistent-runtime"):
            exec_.poll_job(bad_handle)


# ---------------------------------------------------------------------------
# JobExecutor: collect after terminal (V1 contract)
# ---------------------------------------------------------------------------

class TestJobExecutorCollect:
    def test_collect_after_completed_returns_outcome(self) -> None:
        rt = FakeJobRuntime(poll_sequence=["running", "completed"])
        exec_, _ = _full_executor(runtime=rt)
        handle, _ = exec_.start_job(_skill(), SkillExecutionRequest(), _linux_nvidia_req())
        assert handle is not None

        # Poll until terminal.
        while exec_.poll_job(handle) != "completed":
            pass

        # Collect only after terminal — V1 contract.
        outcome = exec_.collect_job(handle)
        assert outcome.success is True
        assert outcome.exit_code == 0
        assert "model" in outcome.artifacts

    def test_collect_is_idempotent(self) -> None:
        rt = FakeJobRuntime(poll_sequence=["completed"])
        exec_, _ = _full_executor(runtime=rt)
        handle, _ = exec_.start_job(_skill(), SkillExecutionRequest(), _linux_nvidia_req())
        assert handle is not None
        exec_.poll_job(handle)  # confirm terminal

        outcome1 = exec_.collect_job(handle)
        outcome2 = exec_.collect_job(handle)
        assert outcome1 == outcome2

    def test_collect_unknown_runtime_raises(self) -> None:
        exec_, _ = _full_executor()
        bad_handle = JobHandle(
            job_id="x", runtime_id="nonexistent-runtime", started_at="2026-01-01T00:00:00+00:00"
        )
        with pytest.raises(RuntimeError, match="nonexistent-runtime"):
            exec_.collect_job(bad_handle)


# ---------------------------------------------------------------------------
# JobExecutor: cancellation
# ---------------------------------------------------------------------------

class TestJobExecutorCancellation:
    def test_cancel_from_running_state(self) -> None:
        rt = FakeJobRuntime(poll_sequence=["running", "running"])
        exec_, _ = _full_executor(runtime=rt)
        handle, result = exec_.start_job(_skill(), SkillExecutionRequest(), _linux_nvidia_req())
        assert handle is not None
        assert result.status == "started"

        exec_.poll_job(handle)  # -> running
        exec_.cancel_job(handle)
        assert exec_.poll_job(handle) == "cancelled"

        outcome = exec_.collect_job(handle)
        assert outcome.success is False
        assert outcome.error_message == "cancelled"

    def test_cancel_from_started_state(self) -> None:
        """cancel() is valid in 'started' state (before first poll)."""
        rt = FakeJobRuntime(poll_sequence=["running"])
        exec_, _ = _full_executor(runtime=rt)
        handle, result = exec_.start_job(_skill(), SkillExecutionRequest(), _linux_nvidia_req())
        assert handle is not None
        assert result.status == "started"

        # Cancel immediately, before any poll.
        exec_.cancel_job(handle)
        status = exec_.poll_job(handle)
        assert status == "cancelled"

        outcome = exec_.collect_job(handle)
        assert outcome.success is False

    def test_cancel_unknown_runtime_raises(self) -> None:
        exec_, _ = _full_executor()
        bad_handle = JobHandle(
            job_id="x", runtime_id="nonexistent-runtime", started_at="2026-01-01T00:00:00+00:00"
        )
        with pytest.raises(RuntimeError, match="nonexistent-runtime"):
            exec_.cancel_job(bad_handle)


# ---------------------------------------------------------------------------
# JobResult properties
# ---------------------------------------------------------------------------

class TestJobResultProperties:
    def test_terminal_statuses_are_terminal(self) -> None:
        from cv_agent.execution.models import ExecutionEvidence
        for status in ("completed", "failed", "cancelled", "host_mismatch", "rejected"):
            from cv_agent.execution.jobs.models import JobResult
            r = JobResult(
                skill_id="s",
                job_id=None,
                status=status,  # type: ignore[arg-type]
                evidence=ExecutionEvidence(None, None, None, None),
            )
            assert r.terminal is True, f"{status} should be terminal"

    def test_non_terminal_statuses_are_not_terminal(self) -> None:
        from cv_agent.execution.models import ExecutionEvidence
        for status in ("not_submitted", "started", "running"):
            from cv_agent.execution.jobs.models import JobResult
            r = JobResult(
                skill_id="s",
                job_id=None,
                status=status,  # type: ignore[arg-type]
                evidence=ExecutionEvidence(None, None, None, None),
            )
            assert r.terminal is False, f"{status} should not be terminal"

    def test_ok_is_true_only_for_completed(self) -> None:
        from cv_agent.execution.models import ExecutionEvidence
        from cv_agent.execution.jobs.models import JobResult
        ok = JobResult(
            skill_id="s", job_id="j", status="completed",
            evidence=ExecutionEvidence(None, None, None, None),
        )
        not_ok = JobResult(
            skill_id="s", job_id=None, status="failed",
            evidence=ExecutionEvidence(None, None, None, None),
        )
        assert ok.ok is True
        assert not_ok.ok is False

    def test_as_dict_is_serialisable(self) -> None:
        import json
        from cv_agent.execution.models import ExecutionEvidence
        from cv_agent.execution.jobs.models import JobResult
        r = JobResult(
            skill_id="s", job_id="j", status="started",
            evidence=ExecutionEvidence("b1", "rt1", "2026-01-01T00:00:00+00:00", None),
        )
        d = r.as_dict()
        # Must be JSON-serialisable (checkpoint safety).
        json.dumps(d)
        assert d["skill_id"] == "s"
        assert d["status"] == "started"


# ---------------------------------------------------------------------------
# runtime_id collision guard
# ---------------------------------------------------------------------------

class TestRuntimeIdCollisionGuard:
    def test_collision_raises_at_construction(self) -> None:
        from cv_agent.execution.models import RuntimeOutcome

        @dataclass
        class DualRuntime:
            runtime_id: str = "shared-id"

            def invoke(self, skill: Skill, request: SkillExecutionRequest) -> RuntimeOutcome:
                return RuntimeOutcome(success=True)

        reg = ExecutionBindingRegistry()
        binding = _binding(runtime_id="shared-id")
        reg.register_binding(binding)
        reg.register_runtime(DualRuntime())  # type: ignore[arg-type]

        job_rt = FakeJobRuntime(runtime_id="shared-id")
        with pytest.raises(ValueError, match="shared-id"):
            JobExecutor(
                registry=reg,
                job_runtimes={"shared-id": job_rt},
                host_verifier=_passing_verifier(),
            )

    def test_no_collision_when_ids_are_distinct(self) -> None:
        from cv_agent.execution.models import RuntimeOutcome

        @dataclass
        class SyncRuntime:
            runtime_id: str = "sync-rt"

            def invoke(self, skill: Skill, request: SkillExecutionRequest) -> RuntimeOutcome:
                return RuntimeOutcome(success=True)

        reg = ExecutionBindingRegistry()
        reg.register_binding(_binding(runtime_id="job-rt"))
        reg.register_runtime(SyncRuntime())  # type: ignore[arg-type]

        job_rt = FakeJobRuntime(runtime_id="job-rt")
        # Should not raise — distinct IDs.
        exec_ = JobExecutor(
            registry=reg,
            job_runtimes={"job-rt": job_rt},
            host_verifier=_passing_verifier(),
        )
        assert exec_.can_start("job-skill") is True
