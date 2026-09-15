"""
cv_agent.execution.binding — ExecutionBinding + ExecutionBindingRegistry.

The layer between a discovered Skill and a SkillExecutor:

    Skill --(skill_id)--> ExecutionBinding --(runtime_id)--> ExecutionRuntime

`ExecutionRuntime` is deliberately a narrow Protocol so a binding is never
coupled to Claude Code, Codex, a specific NVIDIA tool, or any other concrete
runtime (requirement 4/7) — new runtimes plug in by implementing the
protocol and being registered, not by editing this module or SkillExecutor.

No binding is registered anywhere in this codebase by default (see
ADR-0009 §5: inspection of the real installed skill environment found no
generic, verified invocation mechanism — every SKILL.md is prose written for
an LLM agent to read and act on with its own tools, not a program with a
stable I/O contract this registry could bind to honestly). Bindings exist so
tests, and any future genuinely-verified adapter, have somewhere to register
into — not because one is registered today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from cv_agent.execution.models import ApprovalPolicy, RuntimeOutcome, SkillExecutionRequest
from cv_agent.skills.models import Skill


class ExecutionRuntime(Protocol):
    """Something that can actually run a skill, given inputs."""

    runtime_id: str
    """Stable identifier, stored in ExecutionBinding.runtime_id and looked up
    in ExecutionBindingRegistry — never inferred, never guessed."""

    def invoke(self, skill: Skill, request: SkillExecutionRequest) -> RuntimeOutcome:
        """
        Run the skill. Must not raise for an ordinary failure — report it via
        `RuntimeOutcome(success=False, error_message=...)` instead; the
        executor treats an actual exception as a distinct "runtime_error"
        case (a bug in the runtime, not an ordinary failed run) but handles
        both the same way in the returned status ("failed").
        """
        ...


@dataclass(frozen=True)
class ExecutionBinding:
    """
    Declares that `skill_id` can be executed via `runtime_id`, under what
    approval policy, and whether that pairing has actually been verified.

    `verified=False` exists for the same reason capability status "planned"
    exists (ADR-0001 §8a, D-009): a binding can be *declared* without being
    *proven* to work. SkillExecutor treats an unverified binding the same as
    no binding at all — declaring a binding is not evidence it functions.
    """

    skill_id: str
    binding_id: str
    runtime_id: str
    approval_policy: ApprovalPolicy
    verified: bool
    description: str = ""


@dataclass
class ExecutionBindingRegistry:
    """
    Deterministic, inspectable registry of bindings and runtimes.

    Deterministic: lookups are exact dict gets, `list_bindings()` is sorted
    by skill_id — no scoring, no fuzzy matching, no LLM. Inspectable: every
    registered binding and runtime can be listed without executing anything,
    which is what the `executions` CLI command does.
    """

    _bindings: dict[str, ExecutionBinding] = field(default_factory=dict, init=False, repr=False)
    _runtimes: dict[str, ExecutionRuntime] = field(default_factory=dict, init=False, repr=False)

    def register_binding(self, binding: ExecutionBinding) -> None:
        self._bindings[binding.skill_id] = binding

    def register_runtime(self, runtime: ExecutionRuntime) -> None:
        self._runtimes[runtime.runtime_id] = runtime

    def get_binding(self, skill_id: str) -> ExecutionBinding | None:
        return self._bindings.get(skill_id)

    def get_runtime(self, runtime_id: str) -> ExecutionRuntime | None:
        return self._runtimes.get(runtime_id)

    def list_bindings(self) -> list[ExecutionBinding]:
        return sorted(self._bindings.values(), key=lambda b: b.skill_id)

    def list_runtimes(self) -> list[ExecutionRuntime]:
        return sorted(self._runtimes.values(), key=lambda r: r.runtime_id)
