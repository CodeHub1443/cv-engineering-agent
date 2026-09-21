"""
cv_agent.execution.models — Execution request/result data model.

Kept independent of `cv_agent.skills.models.Skill` the same way `Skill` is
kept independent of `RegistryItem` (see skills/models.py's docstring): a
`Skill` describes what was discovered; a `SkillExecutionResult` describes
what happened (or didn't) when execution was attempted against it. Neither
type may claim more than it actually knows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SkillExecutionStatus = Literal["not_executable", "started", "completed", "failed", "rejected"]
"""
- not_executable: no verified execution binding exists for this skill (or the
  binding points at an unregistered runtime). Nothing was attempted.
- rejected: a binding exists but execution was not permitted — either the
  binding's approval policy is "rejected" outright, or it is
  "approval_required" and the request did not carry a granted approval.
  Nothing was attempted.
- started: execution has been handed to the runtime but not yet resolved.
  Not reachable from `SkillExecutor.execute()` today — that call is
  synchronous and always returns a terminal status. Reserved for a future
  asynchronous/long-running runtime (see ADR-0009 Revisit trigger).
- completed: the runtime ran and reported success.
- failed: the runtime ran (or raised) and did not report success.
"""

ApprovalPolicy = Literal["allowed", "approval_required", "rejected"]
"""
The three states requirement 9 asks for, attached to a binding rather than a
request: "allowed" (no gate), "approval_required" (gated — see
docs/APPROVALS.md, [P§24]; the caller must supply `SkillExecutionRequest.
approved=True` after obtaining it through whatever process APPROVALS.md
describes — that process is not implemented by this module), "rejected"
(never permitted through this binding, e.g. a read-only/advisory skill that
should never be invoked as a side-effecting action).
"""

ExecutionErrorCategory = Literal[
    "no_binding",
    "binding_not_verified",
    "approval_denied",
    "runtime_error",
    "binding_mismatch",
]
"""
`binding_mismatch` (ADR-0003 §10, ADR-0009 §14): what would run is not what was
approved — the execution pin is unusable, or the live binding/runtime differs
from it. Terminal and fail-closed; the message lists the differing codes."""


@dataclass(frozen=True)
class SkillExecutionRequest:
    """What the caller is asking a skill to do, and under what authorization."""

    inputs: dict[str, Any] = field(default_factory=dict)
    """Skill-specific parameters. Opaque to the executor and binding registry
    — only the runtime a binding points at knows how to interpret these."""
    task: str | None = None
    """Optional natural-language task this execution serves, for evidence
    trails (e.g. the string passed to `CVAgent.resolve()`)."""
    requested_by: str = "agent"
    approved: bool = False
    """True only if the caller has already obtained whatever approval
    docs/APPROVALS.md requires for this action. The executor trusts this
    flag — it does not itself implement the approval workflow — so callers
    must not set it to True without having actually gone through that gate."""
    expected_binding_pin: dict[str, Any] | None = None
    """The execution pin (ADR-0003 §10.4, ADR-0009 §14) the approval was
    granted for. `None` means NOT SUPPLIED — it cannot express "no binding at
    capture". A supplied pin is compared against the executor's own single
    registry read; an `approval_required` execution without one is refused
    even when `approved` is True (rule E1, `SkillExecutor.execute()`)."""


@dataclass(frozen=True)
class ExecutionEvidence:
    """Provenance of one execution attempt — never fabricated, all-or-nothing."""

    binding_id: str | None
    runtime_id: str | None
    started_at: str | None
    completed_at: str | None


@dataclass(frozen=True)
class ExecutionError:
    category: ExecutionErrorCategory
    message: str


@dataclass(frozen=True)
class SkillExecutionResult:
    skill_id: str
    status: SkillExecutionStatus
    evidence: ExecutionEvidence
    output: dict[str, Any] | None = None
    error: ExecutionError | None = None

    @property
    def ok(self) -> bool:
        return self.status == "completed"


@dataclass(frozen=True)
class RuntimeOutcome:
    """What an `ExecutionRuntime.invoke()` call reports back to the executor."""

    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
