"""
cv_agent.execution.executor — SkillExecutor.

Provider/runtime-agnostic: this module never imports or names a specific
runtime (Claude Code, Codex, a DeepStream/TAO/TensorRT tool, ...). It only
knows the ExecutionBinding / ExecutionRuntime protocols from `binding.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from cv_agent.execution.binding import ExecutionBinding, ExecutionBindingRegistry
from cv_agent.execution.models import (
    ExecutionError,
    ExecutionEvidence,
    SkillExecutionRequest,
    SkillExecutionResult,
)
from cv_agent.skills.models import Skill


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SkillExecutor:
    """
    Executes a resolved Skill through whatever ExecutionBinding the registry
    has for it — and fails safely, with a structured result, when it can't.

    This class owns exactly one responsibility: given (Skill, request),
    decide whether execution is possible and permitted, and if so, delegate
    to the bound runtime and report what happened. It does not:
      - discover skills (cv_agent.skills) or decide which one to use
        (cv_agent.skills.resolver / cv_agent.requirements) — those precede
        this;
      - implement the human-approval workflow docs/APPROVALS.md describes —
        it only *checks* the flag a caller who already went through that
        workflow is expected to set on the request;
      - know what any specific runtime does — that lives behind the
        ExecutionRuntime protocol.
    """

    def __init__(self, registry: ExecutionBindingRegistry) -> None:
        self._registry = registry

    def get_binding(self, skill_id: str) -> ExecutionBinding | None:
        """Inspect-only passthrough to the registry — lets a caller (e.g. a
        LangGraph approval-gate node) read a binding's approval_policy
        without reaching into a private attribute."""
        return self._registry.get_binding(skill_id)

    def can_execute(self, skill_id: str) -> bool:
        """Inspect only — never runs anything. True iff a verified binding
        with a registered runtime exists for skill_id."""
        binding = self._registry.get_binding(skill_id)
        if binding is None or not binding.verified:
            return False
        return self._registry.get_runtime(binding.runtime_id) is not None

    def execute(self, skill: Skill, request: SkillExecutionRequest) -> SkillExecutionResult:
        binding = self._registry.get_binding(skill.skill_id)

        if binding is None:
            return SkillExecutionResult(
                skill_id=skill.skill_id,
                status="not_executable",
                evidence=ExecutionEvidence(None, None, None, None),
                error=ExecutionError(
                    "no_binding",
                    f"No execution binding registered for skill '{skill.skill_id}'.",
                ),
            )

        if not binding.verified:
            return SkillExecutionResult(
                skill_id=skill.skill_id,
                status="not_executable",
                evidence=ExecutionEvidence(binding.binding_id, binding.runtime_id, None, None),
                error=ExecutionError(
                    "binding_not_verified",
                    f"Binding '{binding.binding_id}' for '{skill.skill_id}' is declared "
                    "but not verified — a declared binding is not evidence it works.",
                ),
            )

        if binding.approval_policy == "rejected":
            return SkillExecutionResult(
                skill_id=skill.skill_id,
                status="rejected",
                evidence=ExecutionEvidence(binding.binding_id, binding.runtime_id, None, None),
                error=ExecutionError(
                    "approval_denied",
                    f"Binding '{binding.binding_id}' rejects execution unconditionally.",
                ),
            )

        if binding.approval_policy == "approval_required" and not request.approved:
            return SkillExecutionResult(
                skill_id=skill.skill_id,
                status="rejected",
                evidence=ExecutionEvidence(binding.binding_id, binding.runtime_id, None, None),
                error=ExecutionError(
                    "approval_denied",
                    "Execution requires approval per docs/APPROVALS.md "
                    "([P§24]) and request.approved is False.",
                ),
            )

        runtime = self._registry.get_runtime(binding.runtime_id)
        if runtime is None:
            return SkillExecutionResult(
                skill_id=skill.skill_id,
                status="not_executable",
                evidence=ExecutionEvidence(binding.binding_id, binding.runtime_id, None, None),
                error=ExecutionError(
                    "no_binding",
                    f"Binding '{binding.binding_id}' references unregistered "
                    f"runtime '{binding.runtime_id}'.",
                ),
            )

        started_at = _now_iso()
        try:
            outcome = runtime.invoke(skill, request)
        except Exception as exc:  # noqa: BLE001 — a runtime's own bug, not ours to type
            return SkillExecutionResult(
                skill_id=skill.skill_id,
                status="failed",
                evidence=ExecutionEvidence(
                    binding.binding_id, binding.runtime_id, started_at, _now_iso()
                ),
                error=ExecutionError("runtime_error", str(exc)),
            )
        completed_at = _now_iso()

        if outcome.success:
            return SkillExecutionResult(
                skill_id=skill.skill_id,
                status="completed",
                evidence=ExecutionEvidence(
                    binding.binding_id, binding.runtime_id, started_at, completed_at
                ),
                output=outcome.output,
            )

        return SkillExecutionResult(
            skill_id=skill.skill_id,
            status="failed",
            evidence=ExecutionEvidence(
                binding.binding_id, binding.runtime_id, started_at, completed_at
            ),
            error=ExecutionError(
                "runtime_error", outcome.error_message or "Runtime reported failure."
            ),
        )
