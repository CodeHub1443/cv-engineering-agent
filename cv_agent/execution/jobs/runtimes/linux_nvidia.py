"""
cv_agent.execution.jobs.runtimes.linux_nvidia — LinuxNvidiaJobRuntime.

Concrete JobRuntime that executes a CV workload as a subprocess on a
Linux/NVIDIA host (D-044 execution class, ADR-0013 §2.1).

Why this runtime is verified (ADR-0009 §8 discipline applied to JobRuntime):

- Command contract: the job command is taken from
  `request.inputs["command"]` — a `list[str]` passed directly to
  `subprocess.Popen`. No shell interpretation, no hard-coded tool names,
  no knowledge of what the command does. The runtime is generic; the
  *binding* (one per CV skill) is what names the specific tool.
- stdout/stderr capture: both are captured via `subprocess.PIPE`. The
  process writes into OS pipe buffers while running; `collect()` reads
  them in full after the process is terminal — no output is lost for
  moderate-output jobs (see V1 limitation below).
- Exit code: exit 0 → `success=True`; any non-zero → `success=False`.
  Negative return codes (signal-killed) are treated as failure unless the
  job was explicitly cancelled, in which case `error_message="cancelled"`.
- wall_time_seconds: measured from `time.monotonic()` at `start()` to
  the first `collect()` call. Approximate for short jobs; not representative
  of GPU compute time (no GPU profiling performed here). GPU/VRAM fields in
  JobResourceMetadata remain `None` — only the OS-level subprocess is
  observable from this runtime.
- Cancellation: `cancel()` sends SIGTERM and marks the job. If the process
  does not exit on SIGTERM within `cancel_sigkill_timeout_s` seconds,
  `poll()` sends SIGKILL. The protocol specifies cancel() does not wait;
  the caller must poll() until "cancelled" or "failed".
- Idempotent collect: first call reads the pipes and caches the result;
  subsequent calls return the cached `JobOutcome` directly.

V1 limitations (not defects — documented per CLAUDE.md §1):
- No GPU profiling: peak_vram_mb, gpu_hours, avg_power_watts are always None.
- Pipe buffer: if the subprocess writes more than the OS pipe buffer (typically
  64 KiB / 1 MiB depending on kernel config) without the runtime reading,
  the process will block. V1 is safe for jobs with bounded output.
- No process group: only the direct subprocess PID receives SIGTERM/SIGKILL.
  Child processes spawned by the job are not tracked.
- wall_time_seconds is measured from start() to collect(), not process exit.

Registration (ADR-0009 §8 discipline — not automatic):
  A binding must be explicitly registered for each CV skill that will use
  this runtime. Use `build_binding()` to construct the verified binding, and
  `register_binding()` to install it in the `ExecutionBindingRegistry`.
  Then pass a `LinuxNvidiaJobRuntime` instance in the `job_runtimes` dict
  when constructing `JobExecutor`. Nothing is registered automatically.

  Example:
      from cv_agent.execution.jobs.runtimes.linux_nvidia import (
          LinuxNvidiaJobRuntime, register_binding
      )
      register_binding(agent.execution_bindings, skill_id="my-cv-skill")
      executor = JobExecutor(
          registry=agent.execution_bindings,
          job_runtimes={LinuxNvidiaJobRuntime.RUNTIME_ID: LinuxNvidiaJobRuntime()},
          host_verifier=LinuxNvidiaHostVerifier(),
      )
"""

from __future__ import annotations

import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from cv_agent.execution.binding import (
    ExecutionBinding,
    ExecutionBindingRegistry,
    InputField,
)
from cv_agent.execution.jobs.models import JobHandle, JobOutcome, JobResourceMetadata
from cv_agent.execution.models import ApprovalPolicy, SkillExecutionRequest
from cv_agent.skills.models import Skill

RUNTIME_ID = "linux-nvidia-job-runtime-v1"
BINDING_ID = "linux-nvidia-job-runtime-v1-binding"


class LinuxNvidiaJobRuntime:
    """
    Executes a CV workload as a subprocess on a Linux/NVIDIA host.

    The job command is taken from request.inputs["command"] — a list[str]
    passed directly to subprocess.Popen. stdout and stderr are captured.

    Owns: process lifecycle (start/poll/cancel/collect) for one job each.
    Does not own: host verification (JobExecutor calls HostVerifier before
    start()); binding/approval checks (JobExecutor pre-flight); GPU profiling.
    """

    RUNTIME_ID: str = RUNTIME_ID

    def __init__(
        self,
        runtime_id: str = RUNTIME_ID,
        cancel_sigkill_timeout_s: float = 5.0,
    ) -> None:
        self.runtime_id: str = runtime_id
        self._cancel_sigkill_timeout_s = cancel_sigkill_timeout_s
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._start_times: dict[str, float] = {}
        self._cancel_times: dict[str, float] = {}
        self._cancelled_jobs: set[str] = set()
        self._outcomes: dict[str, JobOutcome] = {}

    # ------------------------------------------------------------------
    # JobRuntime protocol
    # ------------------------------------------------------------------

    def start(self, skill: Skill, request: SkillExecutionRequest) -> JobHandle:
        """
        Spawn the job. Raises RuntimeError if the command is missing or the
        process cannot be launched. JobExecutor catches this and returns
        status="failed".
        """
        command = _extract_command(request.inputs)
        cwd: str | None = request.inputs.get("cwd")
        env: dict[str, str] | None = request.inputs.get("env")

        job_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                cwd=cwd,
                env=env,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise RuntimeError(
                f"LinuxNvidiaJobRuntime: failed to launch command {command!r}: {exc}"
            ) from exc

        self._processes[job_id] = process
        self._start_times[job_id] = time.monotonic()

        return JobHandle(
            job_id=job_id,
            runtime_id=self.runtime_id,
            started_at=started_at,
        )

    def poll(
        self, handle: JobHandle
    ) -> Literal["running", "completed", "failed", "cancelled"]:
        """
        Non-blocking status check. Never raises.
        Returns "running" if the process is still alive.
        Returns "completed"/"failed"/"cancelled" once the process has exited.
        """
        if handle.job_id in self._outcomes:
            return _outcome_to_poll_status(self._outcomes[handle.job_id])

        process = self._processes.get(handle.job_id)
        if process is None:
            return "failed"

        returncode = process.poll()
        if returncode is None:
            # Still running. If we previously sent SIGTERM and the timeout has
            # elapsed, escalate to SIGKILL.
            if handle.job_id in self._cancelled_jobs:
                self._maybe_sigkill(handle.job_id, process)
            return "running"

        # Process has exited.
        if handle.job_id in self._cancelled_jobs:
            return "cancelled"
        return "completed" if returncode == 0 else "failed"

    def cancel(self, handle: JobHandle) -> None:
        """
        Send SIGTERM to the process and mark it as cancelled.
        Does not wait for the process to exit. Call poll() until the status
        is terminal ("cancelled" or "failed").
        Calling cancel() on an already-terminal job is a no-op. Never raises.
        """
        if handle.job_id in self._outcomes:
            return  # Already collected — terminal, no-op.

        process = self._processes.get(handle.job_id)
        if process is None:
            return

        if process.poll() is not None:
            return  # Already exited.

        self._cancelled_jobs.add(handle.job_id)
        self._cancel_times[handle.job_id] = time.monotonic()
        try:
            process.send_signal(signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass  # Already gone — that's fine.

    def collect(self, handle: JobHandle) -> JobOutcome:
        """
        Collect the terminal result. Must only be called after poll() has
        confirmed a terminal status (V1 CONTRACT — ADR-0013 §5.3).
        Idempotent: subsequent calls return the same cached JobOutcome.
        Never raises.
        """
        if handle.job_id in self._outcomes:
            return self._outcomes[handle.job_id]

        process = self._processes.get(handle.job_id)
        if process is None:
            outcome = JobOutcome(
                success=False,
                exit_code=None,
                stdout=None,
                stderr=None,
                error_message="no process record found",
            )
            self._outcomes[handle.job_id] = outcome
            return outcome

        wall_time = time.monotonic() - self._start_times.get(handle.job_id, 0.0)

        try:
            # V1 contract: process is already terminal, so communicate() returns
            # immediately after draining the pipe buffers.
            stdout, stderr = process.communicate(timeout=30.0)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()

        returncode = process.returncode
        cancelled = handle.job_id in self._cancelled_jobs

        resources = JobResourceMetadata(
            wall_time_seconds=wall_time,
            exit_code=returncode,
        )

        if cancelled:
            outcome = JobOutcome(
                success=False,
                exit_code=returncode,
                stdout=stdout or None,
                stderr=stderr or None,
                error_message="cancelled",
                resources=resources,
            )
        else:
            outcome = JobOutcome(
                success=(returncode == 0),
                exit_code=returncode,
                stdout=stdout or None,
                stderr=stderr or None,
                resources=resources,
            )

        self._outcomes[handle.job_id] = outcome
        return outcome

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _maybe_sigkill(self, job_id: str, process: subprocess.Popen[str]) -> None:
        """Escalate to SIGKILL if SIGTERM has not taken effect within the timeout.
        The timeout is measured from when cancel() was called, not from job start."""
        cancel_time = self._cancel_times.get(job_id, time.monotonic())
        elapsed_since_cancel = time.monotonic() - cancel_time
        if elapsed_since_cancel >= self._cancel_sigkill_timeout_s:
            try:
                process.send_signal(signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_command(inputs: dict[str, Any]) -> list[str]:
    command = inputs.get("command")
    if command is None:
        raise RuntimeError(
            "LinuxNvidiaJobRuntime requires request.inputs['command'] to be set "
            "(a non-empty list of strings)."
        )
    if not isinstance(command, list) or not command:
        raise RuntimeError(
            f"request.inputs['command'] must be a non-empty list of strings; "
            f"got {command!r}."
        )
    return command  # type: ignore[return-value]


def _outcome_to_poll_status(
    outcome: JobOutcome,
) -> Literal["completed", "failed", "cancelled"]:
    if outcome.error_message == "cancelled":
        return "cancelled"
    return "completed" if outcome.success else "failed"


# ---------------------------------------------------------------------------
# Registration helpers (explicit opt-in — never called automatically)
# ---------------------------------------------------------------------------

def build_binding(
    skill_id: str,
    *,
    verified: bool = False,
    approval_policy: ApprovalPolicy = "approval_required",
    binding_id: str = BINDING_ID,
    runtime_id: str = RUNTIME_ID,
) -> ExecutionBinding:
    """
    Build an ExecutionBinding for a skill that will run through
    LinuxNvidiaJobRuntime.

    `verified` defaults to False (ADR-0009 §8 discipline). The runtime
    mechanism (subprocess execution, stdout/stderr capture, cancellation) is
    tested by tests/test_linux_nvidia_runtime.py, but that does NOT constitute
    verification of any *specific skill* — verified=True must be set only after
    the caller has personally inspected the skill's implementation, confirmed
    its CLI contract, and documented that inspection (following the trt-perf-
    analysis precedent: script read, exit codes confirmed empirically, side
    effects understood). Pass verified=True explicitly once that work is done:

        build_binding("my-cv-skill", verified=True)

    approval_policy defaults to "approval_required" because running a
    GPU CV workload is an approval-gated action per docs/APPROVALS.md.
    """
    return ExecutionBinding(
        skill_id=skill_id,
        binding_id=binding_id,
        runtime_id=runtime_id,
        approval_policy=approval_policy,
        verified=verified,
        description=(
            "Subprocess execution of a CV skill on a Linux/NVIDIA host. "
            "Command is taken from request.inputs['command']. "
            "stdout/stderr captured; exit code 0 = success. "
            "Host verification (OS + GPU vendor) performed by JobExecutor "
            "before start() is called. Approval required per docs/APPROVALS.md. "
            "See ADR-0013."
        ),
        input_schema=(
            InputField(
                name="command",
                required=True,
                description=(
                    "Non-empty list[str] passed directly to subprocess.Popen. "
                    "No shell interpretation. First element is the executable."
                ),
            ),
            InputField(
                name="cwd",
                required=False,
                description="Working directory for the subprocess. None = inherited.",
            ),
            InputField(
                name="env",
                required=False,
                description=(
                    "dict[str, str] environment for the subprocess. "
                    "None = inherit current process environment."
                ),
            ),
        ),
    )


def register_binding(
    registry: ExecutionBindingRegistry,
    *,
    skill_id: str,
    verified: bool = False,
    approval_policy: ApprovalPolicy = "approval_required",
) -> None:
    """
    Explicit, opt-in wiring — never called automatically.

    Registers a binding for `skill_id` in the registry. `verified` defaults
    to False per ADR-0009 §8 — pass verified=True only after personally
    inspecting the specific skill's implementation (see build_binding()).

    The caller must separately pass a LinuxNvidiaJobRuntime instance in
    the `job_runtimes` dict when constructing JobExecutor:

        from cv_agent.execution.jobs.runtimes.linux_nvidia import (
            LinuxNvidiaJobRuntime, register_binding
        )
        register_binding(registry, skill_id="my-cv-skill", verified=True)
        executor = JobExecutor(
            registry=registry,
            job_runtimes={LinuxNvidiaJobRuntime.RUNTIME_ID: LinuxNvidiaJobRuntime()},
            host_verifier=LinuxNvidiaHostVerifier(),
        )
    """
    registry.register_binding(
        build_binding(skill_id, verified=verified, approval_policy=approval_policy)
    )
