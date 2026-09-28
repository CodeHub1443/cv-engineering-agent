"""
cv_agent.execution.jobs.executor — JobExecutor.

Runs a resolved Skill as a long-running OS process through a registered
JobRuntime, applying the same approval/pin integrity model as SkillExecutor
(ADR-0009) plus host verification before start (ADR-0013 §5.4).

Pre-flight check order (§5.4, must not be reordered):
  1. No binding → not_submitted / no_binding
  2. Binding not verified → not_submitted / binding_not_verified
  3. Policy "rejected" → rejected / approval_denied
  4. Missing pin + approval_required → rejected (E1 rule, ADR-0003 §10)
  5. Pin supplied → pin_mismatch() → rejected / binding_mismatch
  6. approval_required + not approved → rejected / approval_denied
  7. No job runtime registered → not_submitted / no_binding
  8. host_verifier.verify() fails → host_mismatch
  9. runtime.start() raises → failed / runtime_error
 10. success → started
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Mapping

from cv_agent.execution.binding import (
    ExecutionBindingRegistry,
    pin_is_well_formed,
    pin_mismatch,
)
from cv_agent.execution.host import HostRequirement, HostVerifier
from cv_agent.execution.jobs.models import (
    JobHandle,
    JobOutcome,
    JobResult,
)
from cv_agent.execution.jobs.runtime import JobRuntime
from cv_agent.execution.models import (
    ExecutionError,
    ExecutionEvidence,
    SkillExecutionRequest,
)
from cv_agent.skills.models import Skill


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobExecutor:
    """
    Executes a resolved Skill as a long-running OS process through a
    JobRuntime, applying the same approval/pin integrity model as
    SkillExecutor, plus host verification before start.

    Reuses ExecutionBindingRegistry for binding lookup and pin generation.
    Keeps its own job_runtimes dict (keyed by runtime_id) separate from
    the registry's _runtimes dict — a runtime_id names exactly one kind
    of runner. Raises ValueError at construction if a runtime_id appears
    in both dicts (ADR-0013 §3.1).

    Does not replace SkillExecutor — both coexist and use the same registry.
    """

    def __init__(
        self,
        registry: ExecutionBindingRegistry,
        job_runtimes: Mapping[str, JobRuntime],
        host_verifier: HostVerifier,
    ) -> None:
        # Enforce the convention: a runtime_id must not appear in both dicts.
        overlap = set(job_runtimes) & {r.runtime_id for r in registry.list_runtimes()}
        if overlap:
            raise ValueError(
                f"runtime_id(s) {sorted(overlap)} are registered as both an "
                "ExecutionRuntime (in ExecutionBindingRegistry) and a JobRuntime "
                "(in job_runtimes). A runtime_id names exactly one kind of runner "
                "(ADR-0013 §3.1)."
            )
        self._registry = registry
        self._job_runtimes = dict(job_runtimes)
        self._host_verifier = host_verifier

    def can_start(self, skill_id: str) -> bool:
        """Inspect only — never runs anything.
        True iff a verified binding with a registered job runtime exists."""
        binding = self._registry.get_binding(skill_id)
        if binding is None or not binding.verified:
            return False
        return binding.runtime_id in self._job_runtimes

    def start_job(
        self,
        skill: Skill,
        request: SkillExecutionRequest,
        host_requirement: HostRequirement,
    ) -> tuple[JobHandle | None, JobResult]:
        """
        Validate approval/pin (same discipline as SkillExecutor.execute()),
        verify host, then call runtime.start().

        Returns (handle, result). handle is None if the job never started.
        See module docstring for exact pre-flight check order.
        """
        skill_id = skill.skill_id

        # --- step 1: binding exists ---
        binding = self._registry.get_binding(skill_id)
        if binding is None:
            return None, JobResult(
                skill_id=skill_id,
                job_id=None,
                status="not_submitted",
                evidence=ExecutionEvidence(None, None, None, None),
                error=ExecutionError(
                    "no_binding",
                    f"No execution binding registered for skill '{skill_id}'.",
                ),
            )

        # --- step 2: binding is verified ---
        if not binding.verified:
            return None, JobResult(
                skill_id=skill_id,
                job_id=None,
                status="not_submitted",
                evidence=ExecutionEvidence(binding.binding_id, binding.runtime_id, None, None),
                error=ExecutionError(
                    "binding_not_verified",
                    f"Binding '{binding.binding_id}' for '{skill_id}' is declared "
                    "but not verified — a declared binding is not evidence it works.",
                ),
            )

        # --- step 3: policy not unconditionally rejected ---
        if binding.approval_policy == "rejected":
            return None, JobResult(
                skill_id=skill_id,
                job_id=None,
                status="rejected",
                evidence=ExecutionEvidence(binding.binding_id, binding.runtime_id, None, None),
                error=ExecutionError(
                    "approval_denied",
                    f"Binding '{binding.binding_id}' rejects execution unconditionally.",
                ),
            )

        # Read pin + runtime generation in ONE registry call so the same
        # instance whose generation was compared is the one invoked (ADR-0003
        # §10.8, same discipline as SkillExecutor.execute()).
        registration = self._registry.get_runtime_registration(binding.runtime_id)
        generation = registration[1] if registration is not None else None

        pin = request.expected_binding_pin

        # --- step 4: E1 rule — absent pin cannot authorise approval_required ---
        if pin is None and binding.approval_policy == "approval_required":
            return None, JobResult(
                skill_id=skill_id,
                job_id=None,
                status="rejected",
                evidence=ExecutionEvidence(binding.binding_id, binding.runtime_id, None, None),
                error=ExecutionError(
                    "approval_denied",
                    "Job execution requires approval ([P§24]) and approval is not "
                    "bound to an execution snapshot "
                    "(request.expected_binding_pin was not supplied).",
                ),
            )

        # --- step 5: pin mismatch check ---
        if pin is not None:
            if not pin_is_well_formed(pin, skill_id=skill_id):
                codes: tuple[str, ...] = ("execution_pin_malformed",)
            else:
                try:
                    live_binding = binding.pin()
                except ValueError:
                    codes = ("binding.unpinnable",)
                else:
                    codes = pin_mismatch(
                        pin, {"binding": live_binding, "runtime_generation": generation}
                    )
            if codes:
                return None, JobResult(
                    skill_id=skill_id,
                    job_id=None,
                    status="rejected",
                    evidence=ExecutionEvidence(
                        binding.binding_id, binding.runtime_id, None, None
                    ),
                    error=ExecutionError(
                        "binding_mismatch",
                        "job execution pin integrity check failed: " + ", ".join(codes),
                    ),
                )

        # --- step 6: approval required and not approved ---
        if binding.approval_policy == "approval_required" and not request.approved:
            return None, JobResult(
                skill_id=skill_id,
                job_id=None,
                status="rejected",
                evidence=ExecutionEvidence(binding.binding_id, binding.runtime_id, None, None),
                error=ExecutionError(
                    "approval_denied",
                    "Job execution requires approval ([P§24]) and request.approved is False.",
                ),
            )

        # --- step 7: job runtime registered ---
        runtime = self._job_runtimes.get(binding.runtime_id)
        if runtime is None:
            return None, JobResult(
                skill_id=skill_id,
                job_id=None,
                status="not_submitted",
                evidence=ExecutionEvidence(binding.binding_id, binding.runtime_id, None, None),
                error=ExecutionError(
                    "no_binding",
                    f"Binding '{binding.binding_id}' references unregistered "
                    f"job runtime '{binding.runtime_id}'.",
                ),
            )

        # --- step 8: host verification ---
        try:
            ok, reason = self._host_verifier.verify(host_requirement)
        except Exception as exc:  # noqa: BLE001
            ok, reason = False, f"Host verifier raised unexpectedly: {exc}"

        if not ok:
            return None, JobResult(
                skill_id=skill_id,
                job_id=None,
                status="host_mismatch",
                evidence=ExecutionEvidence(binding.binding_id, binding.runtime_id, None, None),
                error=ExecutionError("host_mismatch", reason),  # type: ignore[arg-type]
            )

        # --- step 9: start the job ---
        started_at = _now_iso()
        try:
            handle = runtime.start(skill, request)
        except Exception as exc:  # noqa: BLE001
            return None, JobResult(
                skill_id=skill_id,
                job_id=None,
                status="failed",
                evidence=ExecutionEvidence(
                    binding.binding_id, binding.runtime_id, started_at, _now_iso()
                ),
                error=ExecutionError("runtime_error", str(exc)),
            )

        # --- step 10: success ---
        return handle, JobResult(
            skill_id=skill_id,
            job_id=handle.job_id,
            status="started",
            evidence=ExecutionEvidence(
                binding.binding_id, binding.runtime_id, started_at, None
            ),
        )

    def poll_job(
        self, handle: JobHandle
    ) -> Literal["running", "completed", "failed", "cancelled"]:
        """
        Non-blocking status check. Delegates to the registered JobRuntime.
        Raises RuntimeError if the runtime is not registered (indicates a
        caller bug — should not happen in normal operation).
        """
        runtime = self._job_runtimes.get(handle.runtime_id)
        if runtime is None:
            raise RuntimeError(
                f"poll_job: no JobRuntime registered for runtime_id "
                f"'{handle.runtime_id}' (job_id={handle.job_id!r})."
            )
        return runtime.poll(handle)

    def cancel_job(self, handle: JobHandle) -> None:
        """
        Request cancellation. Valid in any non-terminal state. Does not wait.
        Raises RuntimeError if the runtime is not registered.
        """
        runtime = self._job_runtimes.get(handle.runtime_id)
        if runtime is None:
            raise RuntimeError(
                f"cancel_job: no JobRuntime registered for runtime_id "
                f"'{handle.runtime_id}' (job_id={handle.job_id!r})."
            )
        runtime.cancel(handle)

    def collect_job(self, handle: JobHandle) -> JobOutcome:
        """
        Collect results for a job that has already reached a terminal state.
        Must only be called after poll_job() has confirmed a terminal status
        (ADR-0013 §5.3 V1 CONTRACT — not a blocking wait).
        Raises RuntimeError if the runtime is not registered.
        """
        runtime = self._job_runtimes.get(handle.runtime_id)
        if runtime is None:
            raise RuntimeError(
                f"collect_job: no JobRuntime registered for runtime_id "
                f"'{handle.runtime_id}' (job_id={handle.job_id!r})."
            )
        return runtime.collect(handle)

    # ------------------------------------------------------------------
    # Internal helpers exposed for testing only
    # ------------------------------------------------------------------

    @property
    def _registered_runtime_ids(self) -> frozenset[str]:
        """Inspect-only: the set of registered job runtime IDs."""
        return frozenset(self._job_runtimes)
