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

`ExecutionBinding.input_schema` (`InputField`, ADR-0009 §11) declares a
binding's input contract for a future planning layer (ADR-0010) to read —
metadata only, never a replacement for a runtime's own validation.
`ExecutionBinding.input_field_groups` (`RequiredFieldGroup`, ADR-0009 §12)
extends that with mutually-exclusive ("exactly one of these") groupings a
flat `required: bool` cannot express.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

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
class InputField:
    """
    One declared input a binding's runtime accepts, for a future planning
    layer to read (ADR-0010) — NOT a replacement for the runtime's own
    validation, which remains authoritative (see ADR-0009 §11).

    Deliberately flat, not a general JSON-schema/type system: this
    codebase's one real binding (`trt-perf-analysis`) needs only
    name/required/description/default to answer "do I already have enough
    to attempt a plan, or is something required missing." A richer
    constraint model (e.g. mutually-exclusive field groups) is explicitly
    not attempted here — see ADR-0009 §11's revisit trigger.
    """

    name: str
    required: bool
    description: str
    default: Any | None = None


@dataclass(frozen=True)
class RequiredFieldGroup:
    """
    Declares that at least one of `field_names` must be supplied for the
    binding's input contract to be satisfiable — ADR-0009 §12, resolving
    `docs/state/OPEN_QUESTIONS.md` Q20: `InputField.required: bool` alone is
    flat and cannot express a genuine XOR/oneOf contract, e.g.
    trt-perf-analysis's real `path`/`data` choice (`_build_argv()`: exactly
    one, `ValueError` for both or neither).

    Deliberately presence-only, mirroring `InputField.required`'s own
    presence-only contract (ADR-0009 §11) — `plan_execution()` treats a
    group as satisfied the moment any one of its fields has a known value.
    It does NOT reject "more than one supplied" (e.g. both `path` and
    `data`) at planning time; that stricter, true-XOR "not more than one"
    half stays the runtime's own job (`TrtPerfAnalysisRuntime._build_argv()`
    already raises `ValueError` for that case) — the same "coarser, earlier
    check, not a substitute for the runtime's own validation" posture
    `ExecutionBinding.input_schema` already documents for individual
    required fields.
    """

    kind: Literal["exactly_one"]
    """Only one group semantics exists today — a typed literal, not a bare
    str, so a future second kind (e.g. "all_or_none") is an additive Literal
    member, not a silent string convention."""

    field_names: tuple[str, ...]
    """Every name here must name an `InputField.name` already declared in
    the same `ExecutionBinding.input_schema`, with `required=False` on that
    field — checked by `ExecutionBinding.__post_init__` below. A field
    cannot simultaneously be unconditionally required AND a member of a
    group where only one member is required; that is a contradictory
    contract, rejected at construction, not left to be discovered later."""

    description: str = ""

    def __post_init__(self) -> None:
        if len(self.field_names) < 2:
            raise ValueError(
                "RequiredFieldGroup.field_names needs at least two names to "
                f"mean anything; got {self.field_names!r}."
            )
        if len(set(self.field_names)) != len(self.field_names):
            raise ValueError(
                f"RequiredFieldGroup.field_names has duplicate name(s): {self.field_names!r}."
            )


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
    input_schema: tuple[InputField, ...] = ()
    """Declared input contract, for a future planning layer (ADR-0010) to
    read — see ADR-0009 §11. Empty by default; `SkillExecutor` never reads
    this field, so leaving it empty changes no existing behavior."""

    input_field_groups: tuple[RequiredFieldGroup, ...] = ()
    """Mutually-relevant `InputField` groupings a flat `required: bool`
    cannot express — ADR-0009 §12. Empty by default; changes no existing
    behavior unless deliberately populated. Validated against
    `input_schema` in `__post_init__` below — never trusted unchecked."""

    def __post_init__(self) -> None:
        declared = {f.name for f in self.input_schema}
        for group in self.input_field_groups:
            unknown = [name for name in group.field_names if name not in declared]
            if unknown:
                raise ValueError(
                    f"RequiredFieldGroup {group.field_names!r} references "
                    f"undeclared InputField name(s) {unknown!r} — every group "
                    "member must be declared in input_schema first."
                )
            required_members = [
                f.name for f in self.input_schema
                if f.name in group.field_names and f.required
            ]
            if required_members:
                raise ValueError(
                    f"InputField(s) {required_members!r} are both individually "
                    "required=True and members of an 'exactly_one' "
                    f"RequiredFieldGroup {group.field_names!r} — contradictory "
                    "contract: an unconditionally required field cannot also "
                    "be one option among several."
                )


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
