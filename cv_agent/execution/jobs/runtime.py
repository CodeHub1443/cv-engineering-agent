"""
cv_agent.execution.jobs.runtime — JobRuntime Protocol.

A JobRuntime executes a CV workload as a separate OS process and returns a
handle immediately, unlike ExecutionRuntime.invoke() which blocks until the
run completes (ADR-0009). The two protocols are siblings — they share the
ExecutionBindingRegistry for binding/pin lookup but are resolved through
different dicts (ADR-0013 §3.1).

V1 collect() contract: collect() must only be called AFTER poll() has
returned a terminal status. It is not a blocking wait for a running job —
calling it on a non-terminal job produces undefined behaviour. The
_node_poll_or_collect_job graph node enforces this: it polls until terminal,
then calls collect_job() exactly once (ADR-0013 §5.3, §5.6).
"""

from __future__ import annotations

from typing import Literal, Protocol

from cv_agent.execution.jobs.models import JobHandle, JobOutcome
from cv_agent.execution.models import SkillExecutionRequest
from cv_agent.skills.models import Skill


class JobRuntime(Protocol):
    """
    Protocol for a runtime that executes a CV workload as a separate OS
    process — the job analogue of ExecutionRuntime (ADR-0009).

    runtime_id must be stable and unique across both ExecutionRuntime
    registrations (ExecutionBindingRegistry._runtimes) and JobRuntime
    registrations (JobExecutor.job_runtimes). A runtime_id names exactly
    one kind of runner — registering the same id in both dicts is an error
    (ADR-0013 §3.1; enforced at JobExecutor construction time).
    """

    runtime_id: str

    def start(self, skill: Skill, request: SkillExecutionRequest) -> JobHandle:
        """
        Spawn the job as a separate OS process. Returns a JobHandle
        immediately — does NOT wait for the job to finish.

        On a launch failure, raise RuntimeError (not return a result).
        JobExecutor catches this and returns status="failed".
        """
        ...

    def poll(
        self, handle: JobHandle
    ) -> Literal["running", "completed", "failed", "cancelled"]:
        """
        Non-blocking status check. Never raises — an unreachable or dead
        process should be reported as "failed", not as an exception.
        """
        ...

    def cancel(self, handle: JobHandle) -> None:
        """
        Request cancellation. Valid in any non-terminal state: both
        "started" (process spawned but not yet confirmed running) and
        "running" are valid. Does NOT wait for the process to exit —
        the caller must poll() until "cancelled" or "failed".
        Calling cancel() on an already-terminal job is a no-op.
        Never raises.
        """
        ...

    def collect(self, handle: JobHandle) -> JobOutcome:
        """
        Collect all results for a job that has already reached a terminal
        state (exit code, stdout, stderr, artifacts, resource metadata).
        Idempotent: multiple calls for the same handle return the same outcome.
        Must not raise; an unreachable process returns
        JobOutcome(success=False, exit_code=None, ...).

        V1 CONTRACT: only call this AFTER poll() has returned a terminal
        status. It is not intended to block waiting for a running job —
        doing so would tie up the LangGraph executor thread for the job's
        full duration. An implementation that blocks for a non-terminal job
        is incorrect for V1 graph use (ADR-0013 §5.3).
        """
        ...
