"""
Tests for LinuxNvidiaJobRuntime and the min_vram_mb fix in
LinuxNvidiaHostVerifier.

All tests are deterministic. No NVIDIA hardware, no GPU drivers, no real
CV workloads required. Subprocesses are real OS processes using standard
Unix utilities (echo, sleep, false, bash -c) that are available on any Linux
host. All process invocations are bounded in time: success/failure jobs
exit immediately; cancellation tests use 'sleep 10' but only require SIGTERM
delivery (< 500 ms on Linux).

Coverage:
  - LinuxNvidiaHostVerifier: min_vram_mb fails closed when GPU present
  - LinuxNvidiaJobRuntime: lifecycle (start → poll → collect)
  - stdout/stderr capture
  - non-zero exit code
  - cancellation (SIGTERM, poll until terminal)
  - repeated polling after terminal status returns same status
  - collect() is idempotent (same JobOutcome on second call)
  - process start failure (bad command → RuntimeError)
  - missing command → RuntimeError from start()
  - wall_time_seconds is non-negative in JobOutcome.resources
  - register_binding() puts a verified binding in the registry
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from cv_agent.execution.binding import ExecutionBindingRegistry
from cv_agent.execution.host import (
    HostProfile,
    HostRequirement,
    LinuxNvidiaHostVerifier,
)
from cv_agent.execution.jobs.runtimes.linux_nvidia import (
    RUNTIME_ID,
    LinuxNvidiaJobRuntime,
    build_binding,
    register_binding,
)
from cv_agent.execution.models import SkillExecutionRequest
from cv_agent.skills.models import Skill


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _skill(skill_id: str = "test-cv-job") -> Skill:
    return Skill(
        skill_id=skill_id,
        name=skill_id,
        description="Test CV job skill.",
        source="fixture",
        location=f"/fixtures/{skill_id}/SKILL.md",
    )


def _request(command: list[str], **extra: Any) -> SkillExecutionRequest:
    inputs: dict[str, Any] = {"command": command, **extra}
    return SkillExecutionRequest(inputs=inputs, task="test", requested_by="test-runner")


def _poll_until_terminal(
    runtime: LinuxNvidiaJobRuntime,
    handle: Any,
    timeout_s: float = 5.0,
) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = runtime.poll(handle)
        if status in ("completed", "failed", "cancelled"):
            return status
        time.sleep(0.02)
    return runtime.poll(handle)


# ---------------------------------------------------------------------------
# Host verifier: min_vram_mb fail-closed fix
# ---------------------------------------------------------------------------

class TestMinVramFailClosed:
    """Verify the ADR-0013 §3.3 fail-closed behaviour for min_vram_mb."""

    def _gpu_profile(self) -> HostProfile:
        return HostProfile(
            os="linux",
            gpu_available=True,
            gpu_vendor="nvidia",
            driver_version="535.0",
        )

    def test_min_vram_fails_when_no_gpu(self) -> None:
        profile = HostProfile(
            os="linux", gpu_available=False, gpu_vendor=None, driver_version=None
        )
        verifier = LinuxNvidiaHostVerifier(profile=profile)
        ok, reason = verifier.verify(HostRequirement(os="linux", min_vram_mb=8192))
        assert not ok
        assert "VRAM" in reason

    def test_min_vram_fails_closed_when_gpu_present_but_unmeasured(self) -> None:
        """GPU is present but VRAM cannot be measured — must fail closed."""
        verifier = LinuxNvidiaHostVerifier(profile=self._gpu_profile())
        ok, reason = verifier.verify(
            HostRequirement(os="linux", gpu_vendor="nvidia", min_vram_mb=8192)
        )
        assert not ok
        assert "VRAM" in reason.upper() or "vram" in reason.lower()

    def test_no_min_vram_passes_normally(self) -> None:
        verifier = LinuxNvidiaHostVerifier(profile=self._gpu_profile())
        ok, reason = verifier.verify(HostRequirement(os="linux", gpu_vendor="nvidia"))
        assert ok
        assert reason == ""

    def test_min_vram_none_passes_with_no_gpu(self) -> None:
        """min_vram_mb=None with cpu-only host is fine if gpu_vendor is also None."""
        profile = HostProfile(
            os="linux", gpu_available=False, gpu_vendor=None, driver_version=None
        )
        verifier = LinuxNvidiaHostVerifier(profile=profile)
        ok, _ = verifier.verify(HostRequirement(os="linux"))
        assert ok


# ---------------------------------------------------------------------------
# Lifecycle: start → poll → collect
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_successful_echo_job(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        handle = rt.start(_skill(), _request(["echo", "hello world"]))
        assert handle.runtime_id == rt.runtime_id
        assert handle.job_id  # non-empty

        status = _poll_until_terminal(rt, handle)
        assert status == "completed"

        outcome = rt.collect(handle)
        assert outcome.success is True
        assert outcome.exit_code == 0
        assert outcome.stdout is not None
        assert "hello world" in outcome.stdout

    def test_stderr_captured(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        handle = rt.start(
            _skill(), _request(["bash", "-c", "echo err_msg >&2"])
        )
        status = _poll_until_terminal(rt, handle)
        assert status == "completed"
        outcome = rt.collect(handle)
        assert outcome.stderr is not None
        assert "err_msg" in outcome.stderr

    def test_non_zero_exit_code(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        handle = rt.start(_skill(), _request(["bash", "-c", "exit 42"]))
        status = _poll_until_terminal(rt, handle)
        assert status == "failed"
        outcome = rt.collect(handle)
        assert outcome.success is False
        assert outcome.exit_code == 42

    def test_wall_time_seconds_non_negative(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        handle = rt.start(_skill(), _request(["true"]))
        _poll_until_terminal(rt, handle)
        outcome = rt.collect(handle)
        assert outcome.resources.wall_time_seconds is not None
        assert outcome.resources.wall_time_seconds >= 0.0

    def test_exit_code_in_resources(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        handle = rt.start(_skill(), _request(["true"]))
        _poll_until_terminal(rt, handle)
        outcome = rt.collect(handle)
        assert outcome.resources.exit_code == 0

    def test_gpu_resource_fields_absent(self) -> None:
        """V1: GPU profiling is not implemented — fields must be None."""
        rt = LinuxNvidiaJobRuntime()
        handle = rt.start(_skill(), _request(["true"]))
        _poll_until_terminal(rt, handle)
        outcome = rt.collect(handle)
        assert outcome.resources.gpu_hours is None
        assert outcome.resources.peak_vram_mb is None
        assert outcome.resources.avg_power_watts is None


# ---------------------------------------------------------------------------
# Repeated polling
# ---------------------------------------------------------------------------

class TestRepeatedPolling:
    def test_poll_after_completed_returns_completed(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        handle = rt.start(_skill(), _request(["true"]))
        _poll_until_terminal(rt, handle)
        assert rt.poll(handle) == "completed"
        assert rt.poll(handle) == "completed"

    def test_poll_after_failed_returns_failed(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        handle = rt.start(_skill(), _request(["false"]))
        _poll_until_terminal(rt, handle)
        assert rt.poll(handle) == "failed"
        assert rt.poll(handle) == "failed"

    def test_poll_after_collect_is_still_terminal(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        handle = rt.start(_skill(), _request(["echo", "x"]))
        _poll_until_terminal(rt, handle)
        rt.collect(handle)
        assert rt.poll(handle) == "completed"


# ---------------------------------------------------------------------------
# Idempotent collect()
# ---------------------------------------------------------------------------

class TestCollectIdempotent:
    def test_collect_twice_returns_same_outcome(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        handle = rt.start(_skill(), _request(["echo", "idempotent"]))
        _poll_until_terminal(rt, handle)
        outcome1 = rt.collect(handle)
        outcome2 = rt.collect(handle)
        assert outcome1 == outcome2

    def test_collect_preserves_stdout(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        handle = rt.start(_skill(), _request(["echo", "keep me"]))
        _poll_until_terminal(rt, handle)
        first = rt.collect(handle)
        second = rt.collect(handle)
        assert first.stdout == second.stdout
        assert "keep me" in (first.stdout or "")


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

class TestCancellation:
    def test_cancel_long_running_job(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        handle = rt.start(_skill(), _request(["sleep", "30"]))
        # Give the process a moment to start.
        time.sleep(0.05)
        rt.cancel(handle)
        status = _poll_until_terminal(rt, handle, timeout_s=5.0)
        assert status in ("cancelled", "failed")

    def test_cancel_marks_outcome_not_success(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        handle = rt.start(_skill(), _request(["sleep", "30"]))
        time.sleep(0.05)
        rt.cancel(handle)
        _poll_until_terminal(rt, handle, timeout_s=5.0)
        outcome = rt.collect(handle)
        assert outcome.success is False

    def test_cancel_already_terminal_is_noop(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        handle = rt.start(_skill(), _request(["true"]))
        _poll_until_terminal(rt, handle)
        rt.cancel(handle)  # must not raise
        assert rt.poll(handle) == "completed"

    def test_cancel_sets_error_message(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        handle = rt.start(_skill(), _request(["sleep", "30"]))
        time.sleep(0.05)
        rt.cancel(handle)
        _poll_until_terminal(rt, handle, timeout_s=5.0)
        outcome = rt.collect(handle)
        assert outcome.error_message == "cancelled"


# ---------------------------------------------------------------------------
# Process start failure
# ---------------------------------------------------------------------------

class TestProcessStartFailure:
    def test_nonexistent_command_raises(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        with pytest.raises(RuntimeError, match="failed to launch command"):
            rt.start(_skill(), _request(["/nonexistent/command/that/does/not/exist"]))

    def test_missing_command_key_raises(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        req = SkillExecutionRequest(inputs={}, task="test", requested_by="test")
        with pytest.raises(RuntimeError, match="command"):
            rt.start(_skill(), req)

    def test_empty_command_list_raises(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        with pytest.raises(RuntimeError, match="command"):
            rt.start(_skill(), _request([]))


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------

class TestRegistrationHelpers:
    def test_build_binding_is_verified(self) -> None:
        binding = build_binding("my-cv-skill")
        assert binding.verified is True
        assert binding.runtime_id == RUNTIME_ID
        assert binding.skill_id == "my-cv-skill"

    def test_build_binding_default_approval_required(self) -> None:
        binding = build_binding("my-cv-skill")
        assert binding.approval_policy == "approval_required"

    def test_register_binding_puts_binding_in_registry(self) -> None:
        registry = ExecutionBindingRegistry()
        register_binding(registry, skill_id="my-cv-skill")
        binding = registry.get_binding("my-cv-skill")
        assert binding is not None
        assert binding.verified is True
        assert binding.runtime_id == RUNTIME_ID

    def test_runtime_id_constant(self) -> None:
        rt = LinuxNvidiaJobRuntime()
        assert rt.runtime_id == RUNTIME_ID
        assert LinuxNvidiaJobRuntime.RUNTIME_ID == RUNTIME_ID
