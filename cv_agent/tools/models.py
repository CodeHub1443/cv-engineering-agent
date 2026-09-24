"""
cv_agent.tools.models — Tool request/result data model.

See ADR-0005 §5. Deliberately shape-symmetric to `cv_agent.execution.models`
(ADR-0009) so a caller does not have to learn two unrelated vocabularies, but
never importing from it — this package is a leaf; `cv_agent.execution` may
depend on `cv_agent.tools` in the future, never the reverse (ADR-0005 §2/§3).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Literal, NewType

ToolId = NewType("ToolId", str)
"""
The identity ADR-0001 §5 proposed (`NewType("ToolId", str)`) but, per its own
§8a, never implemented. This is the first concrete definition. Used
consistently as the type of every tool_id-bearing field/parameter in this
package (ADR-0005 §11 finding #6). If ADR-0001 is later accepted, its
`Skill.requires_tools: tuple[ToolId, ...]` should import this type rather
than redefining a second one — not a dependency either package has on the
other today.
"""

ToolTransport = Literal["local", "subprocess", "http", "mcp"]
"""How a ToolInvoker actually reaches whatever it invokes. No transport is
implemented by this ADR/package — this is declarative metadata only."""

ToolResultStatus = Literal["not_executable", "started", "completed", "failed", "rejected"]
"""
- not_executable: no verified, registered ToolInvoker exists for this tool_id
  (or a supplied pin does not match the live spec/invoker registration).
  Nothing was attempted.
- rejected: a spec exists but invocation was not permitted — the spec's
  approval_policy is "rejected" outright, or it is "approval_required" and
  the request did not carry a granted approval (or any approval_required
  invocation with no expected_tool_pin at all — rule mirrors ADR-0003 §10's
  E1). Nothing was attempted.
- started: handed to the invoker but not yet resolved. Not reachable from
  `ToolExecutor.invoke()` today — that call is synchronous and always
  returns a terminal status. Reserved for a future asynchronous transport
  (`http`/`mcp`), mirroring `cv_agent.execution.models.SkillExecutionStatus`'s
  identical treatment of "started" (ADR-0009 §3).
- completed: the invoker ran and reported success.
- failed: the invoker ran (or raised) and did not report success.
"""

ToolErrorCategory = Literal[
    "no_tool", "tool_not_verified", "approval_denied", "transport_error", "tool_mismatch"
]
"""
Shape mirrors `cv_agent.execution.models.ExecutionErrorCategory` exactly
(no_binding/binding_not_verified/approval_denied/runtime_error/
binding_mismatch -> no_tool/tool_not_verified/approval_denied/
transport_error/tool_mismatch).

`tool_mismatch` (ADR-0005 §11 findings #1/#2): what would run is not what
was pinned — the tool pin is unusable, or the live spec/invoker registration
differs from it. Terminal and fail-closed; the message lists the differing
codes. This is the tool-boundary expression of the exact same integrity
check ADR-0003 §10/ADR-0009 §14 already enforce for skills — not a
different security model.

No `invalid_input` category exists (removed from the first draft, ADR-0005
§11 finding #11): this boundary never validates `ToolRequest.inputs` against
`ToolSpec.input_schema`/`input_field_groups` — those are planning/
description metadata only (see `ToolSpec` below). An invoker's own
input-shape rejection is an ordinary invoke() failure, reported as
"failed" / "transport_error", exactly how ADR-0009's own
`TrtPerfAnalysisRuntime` reports a bad path/data combination.
"""

ApprovalPolicy = Literal["allowed", "approval_required", "rejected"]
"""
Value-identical to `cv_agent.execution.models.ApprovalPolicy` (ADR-0009 §3).
Deliberately duplicated, not imported (ADR-0005 §11 finding #12's
resolution): importing it would create the exact
`cv_agent.tools -> cv_agent.execution` dependency ADR-0005 §2/§3 forbid, and
a new shared module solely to deduplicate one three-value Literal would be
an abstraction introduced for its own sake. Drift is prevented structurally,
not by convention alone —
`tests/test_tools.py::test_approval_policy_value_set_matches_execution_boundary`
asserts the two Literals' value sets stay identical.
"""


@dataclass(frozen=True)
class ToolInputField:
    """
    One declared input a tool accepts — planning/description metadata only,
    mirroring `cv_agent.execution.binding.InputField` (ADR-0009 §11) exactly,
    duplicated for the same leaf-package reason as `ApprovalPolicy` above.
    Never enforced by `ToolExecutor` — see `ToolSpec.input_schema`.
    """

    name: str
    required: bool
    description: str
    default: Any | None = None


@dataclass(frozen=True)
class ToolRequiredFieldGroup:
    """
    Declares that EXACTLY ONE of `field_names` must be supplied for a tool's
    input contract to be satisfiable — mirrors
    `cv_agent.execution.binding.RequiredFieldGroup` (ADR-0009 §12/§13),
    applying the lesson from Q20 directly rather than repeating its history:
    "exactly_one" from the start, not a presence-only "at least one"
    construct later found to under-enforce a real XOR.

    Like `ToolInputField`, this is planning/description metadata only —
    `ToolExecutor` never enforces it. A future planning/orchestration
    connector would be responsible for rejecting 2+ present members as a
    distinct outcome, exactly as ADR-0010 §15 does for skills; that is
    orchestration's concern (ADR-0005 §2), not this boundary's, and is not
    implemented here.
    """

    kind: Literal["exactly_one"]
    field_names: tuple[str, ...]
    description: str = ""

    def __post_init__(self) -> None:
        if len(self.field_names) < 2:
            raise ValueError(
                "ToolRequiredFieldGroup.field_names needs at least two names to "
                f"mean anything; got {self.field_names!r}."
            )
        if len(set(self.field_names)) != len(self.field_names):
            raise ValueError(
                f"ToolRequiredFieldGroup.field_names has duplicate name(s): "
                f"{self.field_names!r}."
            )


_APPROVAL_POLICIES = ("allowed", "approval_required", "rejected")
_TOOL_SPEC_PIN_KEYS = (
    "tool_id",
    "name",
    "description",
    "transport",
    "side_effecting",
    "approval_policy",
    "verified",
    "input_schema",
    "input_field_groups",
)
_INPUT_FIELD_PIN_KEYS = ("name", "required", "description", "default")
_GROUP_PIN_KEYS = ("kind", "field_names", "description")
_TOOL_TRANSPORTS = ("local", "subprocess", "http", "mcp")


def _json_native(value: Any) -> Any:
    """
    Canonical JSON-native copy of `value` (tuples become lists), or `ValueError`.

    Identical rule to `cv_agent.execution.binding._json_native` (ADR-0003
    §10.4), duplicated for the same leaf-package reason: only `None`,
    `bool`, `int`, finite `float`, `str`, and lists/tuples/dicts (`str`
    keys) of these are accepted.
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
    """The equality form used for tool-pin comparison: type-sensitive (`1`,
    `1.0`, `true` differ), independent of dict key order and list-vs-tuple
    container type, never a call to `==` on arbitrary objects. Identical
    algorithm to `cv_agent.execution.binding.canonical_json`."""
    return json.dumps(_json_native(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class ToolSpec:
    """
    Declares a tool: its identity, transport, approval policy, and whether
    the pairing of this spec with a registered invoker has actually been
    verified.

    `verified=False` exists for the same reason `ExecutionBinding.verified`
    exists (ADR-0009): a spec can be *declared* without being *proven* to
    work. `ToolExecutor` treats an unverified spec the same as no spec at
    all — declaring one is not evidence it functions.

    `input_schema`/`input_field_groups` are planning/description metadata
    ONLY (ADR-0005 §11 finding #11) — `ToolExecutor` never validates
    `ToolRequest.inputs` against either. A `ToolInvoker` implementation (or
    its own transport-specific validation) is the sole authoritative
    enforcement layer, exactly as ADR-0009 §11 states for `InputField`.
    """

    tool_id: ToolId
    name: str
    description: str
    transport: ToolTransport
    side_effecting: bool
    approval_policy: ApprovalPolicy
    input_schema: tuple[ToolInputField, ...] = ()
    input_field_groups: tuple[ToolRequiredFieldGroup, ...] = ()
    verified: bool = False

    def __post_init__(self) -> None:
        declared = {f.name for f in self.input_schema}
        seen_in_group: dict[str, tuple[str, ...]] = {}
        for group in self.input_field_groups:
            unknown = [name for name in group.field_names if name not in declared]
            if unknown:
                raise ValueError(
                    f"ToolRequiredFieldGroup {group.field_names!r} references "
                    f"undeclared ToolInputField name(s) {unknown!r} — every group "
                    "member must be declared in input_schema first."
                )
            required_members = [
                f.name
                for f in self.input_schema
                if f.name in group.field_names and f.required
            ]
            if required_members:
                raise ValueError(
                    f"ToolInputField(s) {required_members!r} are both individually "
                    "required=True and members of an 'exactly_one' "
                    f"ToolRequiredFieldGroup {group.field_names!r} — contradictory "
                    "contract: an unconditionally required field cannot also "
                    "be one option among several."
                )
            for name in group.field_names:
                if name in seen_in_group:
                    raise ValueError(
                        f"ToolInputField {name!r} belongs to more than one "
                        f"ToolRequiredFieldGroup ({seen_in_group[name]!r} and "
                        f"{group.field_names!r}) — a field may be a member of "
                        "at most one group."
                    )
                seen_in_group[name] = group.field_names

    def pin(self) -> dict[str, Any]:
        """
        Canonical snapshot of THIS spec's own fields only — explicit field
        access, declared order, JSON-native, no `dataclasses.asdict()`/
        `repr()`. Mirrors `ExecutionBinding.pin()` (ADR-0009 §14). Does not
        include invoker/generation information — see `ToolRegistry.pin()`,
        which combines the two. Raises `ValueError` if a `ToolInputField.
        default` is not JSON-native (checked here, at the pin boundary, not
        in the constructor).
        """
        return {
            "tool_id": str(self.tool_id),
            "name": self.name,
            "description": self.description,
            "transport": self.transport,
            "side_effecting": self.side_effecting,
            "approval_policy": self.approval_policy,
            "verified": self.verified,
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


@dataclass(frozen=True)
class ToolRequest:
    """What the caller is asking a tool to do, and under what authorization."""

    inputs: dict[str, Any] = field(default_factory=dict)
    """Tool-specific parameters. Opaque to ToolExecutor and ToolRegistry —
    only the invoker a spec is registered against knows how to interpret
    these. Never validated against input_schema/input_field_groups by this
    boundary (ADR-0005 §11 finding #11)."""

    requested_by: str = "agent"

    approved: bool = False
    """True only if the caller has already obtained whatever approval
    docs/APPROVALS.md requires for this action. ToolExecutor trusts this
    flag — it does not itself implement the approval workflow."""

    expected_tool_pin: dict[str, Any] | None = None
    """The tool pin (ADR-0005 §5/§9) the approval — or, for any policy, the
    caller's own integrity expectation — was captured against. `None` means
    NOT SUPPLIED. The expected shape, when supplied, is exactly
    `ToolRegistry.pin(tool_id)`'s return value — `{"spec": ..., "invoker_
    generation": ...}` — never `ToolSpec.pin()` alone."""


@dataclass(frozen=True)
class ToolError:
    category: ToolErrorCategory
    message: str


@dataclass(frozen=True)
class ToolEvidence:
    """
    Provenance of one invocation attempt — never fabricated, all-or-nothing,
    and never copied from a field a `ToolInvoker` itself sets (see
    `ToolOutcome`). Mirrors `ExecutionEvidence`'s role (ADR-0009 §5).

    `invoker_generation` stands in for a separate "invoker_id" field
    deliberately: this boundary's `ToolInvoker.tool_id` already IS the
    tool's own identity (a 1:1 tool/invoker model, simpler than ADR-0009's
    separate skill_id/runtime_id namespaces — ADR-0005 §11's "deliberately
    not changed" note), so a distinct invoker_id field would just repeat
    tool_id; the generation number is the genuinely new audit fact worth
    recording.

    `provenance`/`execution_metadata` are deliberately generic, unpopulated
    placeholder dicts (ADR-0005 §11 finding #4, spec/06's "Tool Result
    Contract"). Type-level only: no backend, no persistence mechanism, no
    concrete schema for either dict's contents is chosen by this ADR/
    package. `ToolExecutor` never populates them from anything an invoker
    reports.
    """

    tool_id: ToolId
    invoker_generation: int | None
    started_at: str | None
    completed_at: str | None
    provenance: dict[str, Any] = field(default_factory=dict)
    execution_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """
    Shape matches `SkillExecutionResult` (skill_id/status/evidence/output/
    error, ADR-0009 §5) field-for-field. Constructed ONLY by `ToolExecutor`
    — see `ToolInvoker`/`ToolOutcome`: a `ToolInvoker` has no way to produce
    one of these directly (ADR-0005 §11 finding #3).
    """

    tool_id: ToolId
    status: ToolResultStatus
    evidence: ToolEvidence
    output: dict[str, Any] | None = None
    error: ToolError | None = None

    @property
    def ok(self) -> bool:
        return self.status == "completed"


@dataclass(frozen=True)
class ToolOutcome:
    """
    What a `ToolInvoker.invoke()` call reports back to `ToolExecutor`.

    Mirrors `RuntimeOutcome` (ADR-0009 §5) exactly, for the identical
    reason: a `ToolInvoker` reports only whether ITS OWN call succeeded and
    what it produced — it has no field to set `tool_id`, `status`, or
    evidence with. Those are `ToolExecutor`'s to assign afterward, from what
    the executor itself knows (the request it made, the identity/generation
    it looked up, its own clock) — never from data an invoker chooses to
    hand back. This is the trust boundary ADR-0005 §11 finding #3 restores.
    """

    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
