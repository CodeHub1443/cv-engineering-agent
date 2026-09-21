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

import json
import math
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
    Declares that EXACTLY ONE of `field_names` must be supplied for the
    binding's input contract to be satisfiable — ADR-0009 §12/§13,
    resolving `docs/state/OPEN_QUESTIONS.md` Q20: `InputField.required:
    bool` alone is flat and cannot express a genuine XOR/oneOf contract,
    e.g. trt-perf-analysis's real `path`/`data` choice (`_build_argv()`:
    exactly one, `ValueError` for both or neither).

    True oneOf/XOR semantics at the planning layer (ADR-0010 §15):
    `plan_execution()` treats a group as satisfied only when exactly one
    of its fields has a known value — zero present is
    `"missing_required_inputs"`, two or more present together is
    `"conflicting_inputs"`, both reported as a distinct, actionable
    `PlanningResult` status before any plan is produced or `approval_gate`
    is ever reached. This still checks *presence and count* only, never a
    field's *value* — `TrtPerfAnalysisRuntime._build_argv()` remains the
    final, authoritative content-level enforcement (already raises
    `ValueError` for both/neither, independent of and unaffected by this
    layer's own check), the same "coarser, earlier check, not a substitute
    for the runtime's own validation" posture `ExecutionBinding.
    input_schema` already documents for individual required fields.
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


_APPROVAL_POLICIES = ("allowed", "approval_required", "rejected")
_BINDING_PIN_KEYS = (
    "skill_id",
    "binding_id",
    "runtime_id",
    "approval_policy",
    "verified",
    "description",
    "input_schema",
    "input_field_groups",
)
_INPUT_FIELD_PIN_KEYS = ("name", "required", "description", "default")
_GROUP_PIN_KEYS = ("kind", "field_names", "description")


def _json_native(value: Any) -> Any:
    """
    Canonical JSON-native copy of `value` (tuples become lists), or `ValueError`.

    Only `None`, `bool`, `int`, finite `float`, `str`, and lists/tuples/dicts
    (`str` keys) of these are accepted. This is the pin/serialization boundary
    check of ADR-0003 section 10.4 - deliberately NOT a constructor restriction
    on `ExecutionBinding`/`InputField`, so declaring a binding is unaffected;
    only pinning one that holds a non-JSON-native default fails.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite float {value!r} is not JSON-native")
        return value
    if isinstance(value, (list, tuple)):
        return [_json_native(v) for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError(f"dict key {k!r} is not a str")
            out[k] = _json_native(v)
        return out
    raise ValueError(f"{type(value).__name__} value is not JSON-native")


def canonical_json(value: Any) -> str:
    """The equality form of ADR-0003 section 10.4: type-sensitive (`1`, `1.0`,
    `true` differ), independent of dict key order and list-vs-tuple container
    type, never a call to `==` on arbitrary objects."""
    return json.dumps(_json_native(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _pin_shape_ok(pin: Any) -> bool:
    """Strict schema of an execution pin (ADR-0003 section 10.4): exact keys,
    exact types, no extras. Never raises."""
    try:
        if not isinstance(pin, dict) or set(pin) != {"binding", "runtime_generation"}:
            return False
        generation = pin["runtime_generation"]
        if generation is not None and (type(generation) is not int or generation < 1):
            return False
        binding = pin["binding"]
        if not isinstance(binding, dict) or set(binding) != set(_BINDING_PIN_KEYS):
            return False
        for key in ("skill_id", "binding_id", "runtime_id", "description"):
            if not isinstance(binding[key], str):
                return False
        if binding["approval_policy"] not in _APPROVAL_POLICIES:
            return False
        if not isinstance(binding["verified"], bool):
            return False
        schema = binding["input_schema"]
        if not isinstance(schema, list):
            return False
        for entry in schema:
            if not isinstance(entry, dict) or set(entry) != set(_INPUT_FIELD_PIN_KEYS):
                return False
            if not isinstance(entry["name"], str) or not isinstance(entry["description"], str):
                return False
            if not isinstance(entry["required"], bool):
                return False
            _json_native(entry["default"])
        groups = binding["input_field_groups"]
        if not isinstance(groups, list):
            return False
        for group in groups:
            if not isinstance(group, dict) or set(group) != set(_GROUP_PIN_KEYS):
                return False
            if not isinstance(group["kind"], str) or not isinstance(group["description"], str):
                return False
            if not _is_str_list(group["field_names"]):
                return False
        return True
    except (ValueError, TypeError):
        return False


def pin_is_well_formed(pin: Any, *, skill_id: str) -> bool:
    """`_pin_shape_ok` plus `binding.skill_id == skill_id` (ADR-0003 10.3)."""
    return _pin_shape_ok(pin) and pin["binding"]["skill_id"] == skill_id


def pin_mismatch(expected: Any, live: dict[str, Any]) -> tuple[str, ...]:
    """
    Compare a supplied pin with the live one. `()` means equal; a malformed
    `expected` is `("execution_pin_malformed",)`; otherwise sorted codes -
    `binding.<key>` per differing binding key, `runtime_registration` when the
    runtime generation differs. Equality is `canonical_json` of each value.
    """
    if not _pin_shape_ok(expected):
        return ("execution_pin_malformed",)
    codes: list[str] = []
    for key in _BINDING_PIN_KEYS:
        if canonical_json(expected["binding"][key]) != canonical_json(live["binding"][key]):
            codes.append(f"binding.{key}")
    if canonical_json(expected["runtime_generation"]) != canonical_json(
        live["runtime_generation"]
    ):
        codes.append("runtime_registration")
    return tuple(sorted(codes))


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
        seen_in_group: dict[str, tuple[str, ...]] = {}
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
            # A field belonging to more than one group would break the
            # "unsatisfied group's members are, by construction, entirely
            # present in missing_inputs" invariant cv_agent.graph.workflow's
            # _node_provide_execution_inputs relies on to reconstruct which
            # groups are still in play from a flat requested-names list —
            # rejected here, at construction, rather than left as a latent
            # correctness gap discovered only if a second grouped binding
            # ever needed it (review finding on PR #40/ADR-0009 §13).
            for name in group.field_names:
                if name in seen_in_group:
                    raise ValueError(
                        f"InputField {name!r} belongs to more than one "
                        f"RequiredFieldGroup ({seen_in_group[name]!r} and "
                        f"{group.field_names!r}) — a field may be a member of "
                        "at most one group."
                    )
                seen_in_group[name] = group.field_names

    def pin(self) -> dict[str, Any]:
        """
        Canonical snapshot of this whole binding (ADR-0003 section 10.4). Every
        key is read by explicit field access - never `dataclasses.asdict`,
        `repr` or object equality - tuples become lists, declared order is
        preserved and significant. Raises `ValueError` if an
        `InputField.default` is not JSON-native (checked here, at the pin
        boundary, not in the constructor).
        """
        return {
            "skill_id": self.skill_id,
            "binding_id": self.binding_id,
            "runtime_id": self.runtime_id,
            "approval_policy": self.approval_policy,
            "verified": self.verified,
            "description": self.description,
            "input_schema": [
                {
                    "name": f.name,
                    "required": f.required,
                    "description": f.description,
                    "default": _json_native(f.default),
                }
                for f in self.input_schema
            ],
            "input_field_groups": [
                {
                    "kind": g.kind,
                    "field_names": list(g.field_names),
                    "description": g.description,
                }
                for g in self.input_field_groups
            ],
        }


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
    _runtimes: dict[str, tuple[ExecutionRuntime, int]] = field(
        default_factory=dict, init=False, repr=False
    )
    """runtime_id -> (runtime, registration generation), replaced by a single
    assignment so instance and generation are always read together
    (ADR-0003 section 10.8)."""

    def register_binding(self, binding: ExecutionBinding) -> None:
        self._bindings[binding.skill_id] = binding

    def register_runtime(self, runtime: ExecutionRuntime) -> None:
        """Generation: first registration 1; the same object again keeps it
        (identical re-registration is not a change); a different object under
        the same `runtime_id` increments it. Only this method maintains the
        generation - writing `_runtimes` directly bypasses it."""
        prior = self._runtimes.get(runtime.runtime_id)
        if prior is None:
            generation = 1
        elif prior[0] is runtime:
            generation = prior[1]
        else:
            generation = prior[1] + 1
        self._runtimes[runtime.runtime_id] = (runtime, generation)

    def get_binding(self, skill_id: str) -> ExecutionBinding | None:
        return self._bindings.get(skill_id)

    def get_runtime(self, runtime_id: str) -> ExecutionRuntime | None:
        entry = self._runtimes.get(runtime_id)
        return entry[0] if entry is not None else None

    def get_runtime_registration(
        self, runtime_id: str
    ) -> tuple[ExecutionRuntime, int] | None:
        """Inspect-only: the registered runtime and its generation from ONE
        dict read, so a caller that invokes this instance is invoking the
        instance whose generation it compared."""
        return self._runtimes.get(runtime_id)

    def pin(self, skill_id: str) -> dict[str, Any] | None:
        """
        The execution pin for `skill_id` (ADR-0003 section 10.2):
        `{"binding": binding.pin(), "runtime_generation": int | None}`, or
        `None` if no binding is registered. `runtime_generation` is `None`
        when the binding's runtime is not registered. Raises `ValueError` if
        the binding cannot be pinned (non-JSON-native default).
        """
        binding = self._bindings.get(skill_id)
        if binding is None:
            return None
        registration = self._runtimes.get(binding.runtime_id)
        return {
            "binding": binding.pin(),
            "runtime_generation": registration[1] if registration is not None else None,
        }

    def list_bindings(self) -> list[ExecutionBinding]:
        return sorted(self._bindings.values(), key=lambda b: b.skill_id)

    def list_runtimes(self) -> list[ExecutionRuntime]:
        return sorted((e[0] for e in self._runtimes.values()), key=lambda r: r.runtime_id)
