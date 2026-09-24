# ADR-0005: Tool / MCP boundary

- **Status:** Accepted (owner: Tanvir, 2026-09-24 — reviewed with no blockers,
  revised to address all five IMPORTANT findings, then accepted for
  implementation). Implementation: `cv_agent/tools/`, this branch.
- **Date:** 2026-09-24
- **Layer:** execution
- **Canon:** `[P§22]`, `[P§15]`, `[P§19]`, `[P§21]`, `[P§23]`, `[P§34]`
- **Supersedes / Superseded by:** —
- **Issue:** #53

## 1. Context

`docs/architecture/OVERVIEW.md`'s responsibility table lists a **Tools / MCP** row —
"Executable interfaces and their transport boundary `[P§22]`" — with ADR column
"ADR-0005 (not yet written)" and Status "Planned as a generic MCP boundary." The same
row explicitly distinguishes this from `cv_agent/execution/` (ADR-0009), which it
describes as "a narrower execution/invocation boundary for skill bindings
specifically — real, but not the generic tool/MCP transport this row describes."
`docs/roadmap/ROADMAP.md` Phase 2 (Knowledge & research) names ADR-0005 in its Scope
line; Phase 2's Status line (before this session) read "not started... no `cv_agent`
module for retrieval, MCP, or web research exists." **Correction, found during
architecture review:** the first draft of this ADR additionally claimed Phase 3
(Skills & NVIDIA integration) names ADR-0005 too — verified directly against the file
and found false. Phase 3's Scope line names only ADR-0007. Phase 3 is thematically
adjacent through ADR-0009 §2's own explicit non-ownership statement (next bullet), not
through a ROADMAP citation.

`[P§22]` ("MCP's role") states MCP "should eventually provide a standardized boundary
between the agent and external capabilities" spanning knowledge tools, research tools,
GitHub, filesystem, NVIDIA tools, training infrastructure, profiling, and deployment
infrastructure — "the agent should reason about what needs to be done, while tools
provide the ability to do it." `[P§15]` requires discovering and invoking existing
NVIDIA capabilities rather than reimplementing them. `spec/06-tooling-and-mcp.md` (a
non-canonical technical elaboration) already sketches an execution principle ("agents
determine what, tools/workers determine how"), a resolution chain (task → capability →
skill → tool/worker → platform profile → policy → execution → structured result), and
an explicit warning that "MCP is an integration protocol, not the definition of CV
engineering semantics" — MCP-specific transport/authorization/SDK/version details
belong in an adapter layer, not in domain contracts.

**What already exists and must not be duplicated:**

- **ADR-0001** (capability model, still `Proposed` per `docs/state/DECISIONS.md` D-005 —
  not yet accepted) proposes `ToolId = NewType("ToolId", str)` and a `Skill.requires_tools:
  tuple[ToolId, ...]` field in its own §5 interface, but its own §8a interim-correction
  note records this was **never implemented** — no `ToolId` exists anywhere in the
  codebase today. This ADR is the first to give that identity a concrete home.
- **ADR-0007** (skill discovery/resolution, Accepted) owns discovering what skills exist
  and matching a task to them. It explicitly does **not** own "actually invoking a skill
  or tool → tools/MCP layer (not built, `[P§22]`)" — this ADR is that named, still-open
  dependency.
- **ADR-0009** (skill execution boundary, Accepted) owns the `Skill → ExecutionBinding →
  ExecutionRuntime` chain — but scoped, by its own §2, to "attempt to run a **resolved
  Skill**." It has exactly one real, verified binding (`trt-perf-analysis`). Nothing in
  ADR-0009 models a tool call that is not attached to a discovered skill (a research
  fetch, a GitHub call, a filesystem read, a future MCP `tools/call`).
- **`docs/state/OPEN_QUESTIONS.md` Q5** ("Which NVIDIA capabilities are actually
  installed and invocable today? ... Discovery mechanism depends on whether these are
  MCP servers, CLI tools, Python SDKs, or agent skills") is listed as blocking
  ADR-0005 and ADR-0007. ADR-0007 shipped by scoping itself to local filesystem skill
  discovery only, leaving the MCP half of Q5 untouched. **That half is still open and
  is explicitly not resolved by this ADR** (see §10).

Without this ADR, any future non-skill integration (Phase 2 research/knowledge tools,
a GitHub call, a future MCP client) has no shared boundary to build against — it would
either misuse ADR-0009's skill-shaped types for something that is not a skill, or
invent its own ad hoc calling convention, which is exactly the per-integration drift
`[P§34]`'s boundary test and `[P§31]`'s "not a fixed technique list / not hundreds of
hardcoded prompts" both warn against.

## 2. Responsibility (required — `[P§34]`)

- **This owns:** the generic, transport-agnostic contract for declaring and invoking a
  named **tool** — a `ToolSpec`/`ToolInvoker`/`ToolRegistry`/`ToolExecutor` boundary
  that sits underneath both reasoning (which decides *whether* a tool is needed) and
  any future concrete transport (a plain Python callable, a subprocess, an HTTP call,
  or a real MCP client). It owns keeping `[P§22]`'s "agent decides what, tool provides
  how" split enforceable in types, not only in prose.

- **This does NOT own:**
  - deciding whether a tool should be invoked, or which one a task needs → reasoning
    layer (ADR-0008), reached through the existing capability/skill resolution chain
    (ADR-0001/ADR-0007) — unchanged by this ADR;
  - the capability catalogue → ADR-0001, unchanged;
  - discovering or resolving skills → ADR-0007, unchanged; a `Skill` remains
    "specialized procedural knowledge for accomplishing a capability" (`[P§23]`),
    distinct from a `Tool`, which is a raw executable interface a skill (or a
    reasoning node, or orchestration) may call;
  - the skill-specific execution chain `Skill → ExecutionBinding → ExecutionRuntime`
    → ADR-0009, unchanged and not superseded; ADR-0009's consumers (`CVAgent.execute()`,
    `SkillExecutor`, `python -m cv_agent execute`) are not touched, redirected, or
    reimplemented by this ADR;
  - orchestration/workflow state, branching, retries, interrupts → ADR-0003, unchanged;
    this ADR defines what a `Tool` *is* and how a single invocation is *permitted*, never
    when or whether that invocation happens inside a graph node;
  - approval-integrity pinning semantics → ADR-0003 §10 / ADR-0009 §14, unchanged; see
    §9's non-negotiables — this boundary is shaped to interoperate with that machinery,
    not to bypass or duplicate it;
  - selecting an MCP SDK, vendor, or protocol version, or deciding which concrete NVIDIA
    integrations should be MCP-backed vs. CLI/skill-backed → explicitly out of scope
    (`OPEN_QUESTIONS.md` Q5's still-open half, see §10);
  - cost estimation or approval thresholds → Q6/Q19, unresolved and untouched;
  - where the agent or any job it invokes physically executes → Q2, untouched;
  - LLM-native tool/function calling (e.g., a future `tools=[...]` parameter on an
    Anthropic request) → the LLM Gateway (ADR-0002) plus the reasoning layer
    (ADR-0008), unchanged. This boundary is reached only after reasoning has already
    decided to call a specific `tool_id` and constructed a `ToolRequest`; it is not a
    mechanism for an LLM to enumerate, browse, or select among `ToolSpec`s itself, and
    the LLM Gateway must not import `cv_agent.tools` to expose `ToolSpec`s as
    provider-native function-call schemas without a separate, later decision to do so.

- **Why this responsibility does not belong to an existing component:** ADR-0009's
  boundary is keyed on `skill_id` and is deliberately scoped to running a *resolved
  skill* — its own §2 says so. A research-fetch call, a GitHub API call, or a future
  MCP `tools/call` is not a skill invocation: it has no `SKILL.md`, is not subject to
  `SkillInventory` discovery, and may have entirely different approval semantics than
  "run this local Python script." Routing it through `ExecutionBinding`/
  `ExecutionRuntime` via a synthetic `skill_id` would misuse a skill-shaped contract for
  a non-skill concept — the exact concept-collapse `[P§23]` forbids ("these are not
  interchangeable"). `[P§23]`'s own resolution chain already says a skill *requires
  tools*, not that a skill *is* a tool — tools are the more primitive, more general
  concept underneath, with callers beyond skills alone (a reasoning node needing
  research; orchestration needing a filesystem check). A new, narrower layer beneath
  both skills and orchestration is the only placement that keeps that chain intact.

> This section can be answered cleanly: the boundary is new, sits strictly beneath the
> existing skill/capability/orchestration layers, and duplicates none of their state.

## 3. Decision

Introduce `cv_agent/tools/` as a new, dependency-free leaf package defining the generic
tool-invocation boundary: `ToolId`, `ToolSpec` (declarative, transport-tagged metadata,
carrying its own `approval_policy` and a `pin()` method), `ToolInvoker` (a narrow
`Protocol`, one `invoke()` method, shaped symmetrically to — but never substitutable
for — ADR-0009's `ExecutionRuntime`), `ToolRequest`/`ToolResult`/`ToolError`,
`ToolRegistry` (explicit registration only, no auto-discovery, mirroring
`ExecutionBindingRegistry`'s own posture), and `ToolExecutor` (the one fail-safe
decision point — verification, approval-policy, and pin checks — mirroring
`SkillExecutor.execute()`'s branching so the two boundaries cannot silently diverge in
how they treat an unpinned approval-required call). This ADR registers **zero**
`ToolSpec`s and **zero** `ToolInvoker`s, and selects no MCP SDK, vendor, or concrete
integration — it is the boundary only, following the same "types before adapters"
discipline ADR-0009 used for skill execution (§1 there: "building an adapter... would
violate `[P§35]`"). `cv_agent.tools` imports nothing from `cv_agent.execution`,
`cv_agent.skills`, `cv_agent.graph`, or `cv_agent.llm`; those layers may depend on
`cv_agent.tools` once this ADR is accepted and implemented, never the reverse.

**Revised following architecture review (§11):** `ToolRegistry` also tracks a
per-`tool_id` invoker-registration generation (mirroring
`ExecutionBindingRegistry.get_runtime_registration()`) so a replaced `ToolInvoker`
during a pause is detectable, not merely assumed stable; `ToolInvoker.invoke()`
returns a new, narrow `ToolOutcome` rather than the final `ToolResult` directly,
restoring the same runtime/executor trust-boundary split ADR-0009 keeps via
`RuntimeOutcome`; `ToolResult` gains an `evidence: ToolEvidence` field carrying
type-level-only `provenance`/`execution_metadata` placeholders; `ToolResultStatus`
gains a `started` value; and `ToolSpec` gains an optional `ToolRequiredFieldGroup`
construct for mutually-exclusive inputs, specified as `exactly_one` from the start
rather than repeating ADR-0009 §12/§13's own presence-only-then-corrected history.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Route all future tool calls through ADR-0009's existing `ExecutionBinding`/`ExecutionRuntime`, tagging non-skill tools with a synthetic `skill_id` | No new package; one boundary instead of two | ADR-0009 §2 scopes itself explicitly to "attempt to run a resolved Skill"; a synthetic `skill_id` for e.g. a GitHub call would misrepresent the DECLARED/DISCOVERED/EXECUTABLE model ADR-0007 depends on (a tool is not discovered the way a skill is) and would entangle skill-specific approval-pinning (ADR-0003 §10) with calls that may need different approval semantics | Concept collapse; violates `[P§23]` and ADR-0009's own stated boundary |
| Select a concrete MCP SDK now and build a real MCP client as this ADR's deliverable | Matches `[P§22]`'s long-term vision fastest; would unblock Phase 2 research tooling sooner | No MCP server has been verified as installed or authorized in this environment (`OPEN_QUESTIONS.md` Q5 is explicitly still open for exactly this reason); out of this task's own stated scope; would also require deciding transport/authorization policy, which is Q6/Q19-adjacent and not authorized | Out of scope by explicit instruction; premature relative to Q5 |
| No new abstraction — each future integration (research fetch, GitHub, dataset tools, training infra) invents its own calling convention inline where it is used | Zero cost today; nothing to design | Directly reproduces the "hundreds of hardcoded... one-off integrations" anti-pattern `[P§31]`/`[P§34]` name; every future PR re-derives request/result/error shape and re-decides where approval-checking happens, with no shared enforcement point — makes extending ADR-0003 §10's pinning discipline to tools unenforceable, since there is no shared choke point to enforce it at | Violates `[P§34]`'s boundary-first discipline |
| Fold tool-calling into orchestration nodes (each LangGraph node defines its own tool inline) | Matches common LangGraph "tool node" patterns in the wider ecosystem | Violates ADR-0003's own stated boundary ("Does NOT own: domain knowledge, skill registry... retrieval") and the "LangGraph nodes holding domain knowledge inline" anti-pattern `docs/architecture/OVERVIEW.md` itself names | Reproduces a named anti-pattern in this repo's own docs |

## 5. Interface

Types and protocol signatures only. No implementation bodies.

> **Revised following architecture review — see §11 for the full list of findings and
> what changed.** The first-draft interface is not shown separately; this is the
> current, single proposed interface.

```python
# module: cv_agent.tools.models
from dataclasses import dataclass, field
from typing import Any, Literal, NewType, Protocol

ToolId = NewType("ToolId", str)
# First concrete definition of the identity ADR-0001 §5 proposed but never implemented
# (ADR-0001 §8a: "does not build... typed SkillId/ToolId/AgentId"). If ADR-0001 is
# later accepted and implemented, its Skill.requires_tools field should import this
# type rather than redefining a second one — a forward-compatibility note, not a
# dependency either package has on the other today (see §10). Used consistently as
# the type of every tool_id-bearing field/parameter below (§11 finding #6 — the first
# draft declared this type but never used it anywhere in its own interface).

ToolTransport = Literal["local", "subprocess", "http", "mcp"]

ToolResultStatus = Literal["not_executable", "started", "completed", "failed", "rejected"]
# Value-set now identical to cv_agent.execution.models.SkillExecutionStatus (ADR-0009
# §3). "not_available" (first draft) renamed to "not_executable" — no documented
# reason existed for the naming drift (§11 finding #10). "started" is new (§11
# finding #5): an http/mcp transport is far more likely to need an in-progress state
# than the skill boundary's synchronous-subprocess model was; ADR-0009 §3 added the
# same state pre-emptively, for the same reason, and documents it as unreachable from
# a synchronous executor — true here too: no ToolExecutor branch described below
# produces "started"; it is reserved for a future asynchronous ToolInvoker.

ToolErrorCategory = Literal[
    "no_tool", "tool_not_verified", "approval_denied", "transport_error", "tool_mismatch",
]
# Shape now mirrors cv_agent.execution.models.ExecutionErrorCategory exactly
# (no_binding/binding_not_verified/approval_denied/runtime_error/binding_mismatch ->
# no_tool/tool_not_verified/approval_denied/transport_error/tool_mismatch).
# "tool_mismatch" is new (§11 findings #1/#2): reported when a supplied
# expected_tool_pin does not match the live ToolSpec + invoker registration — see
# ToolRegistry.pin()/tool_pin_mismatch() below. It names a registration/pin mismatch
# only; it is the tool-boundary expression of the exact same integrity check ADR-0003
# §10/ADR-0009 §14 already enforce for skills, using this package's own types instead
# of importing theirs (§2/§3) — not a different security model.
# "invalid_input" (first draft) is removed, not silently deferred (§11 finding #11):
# this boundary does not validate request.inputs against input_schema at all (see
# ToolSpec.input_schema below), and no branch described below ever produces it. An
# invoker's own input-shape rejection is reported as an ordinary invoke() failure —
# status="failed" / category="transport_error" — exactly how ADR-0009's own
# TrtPerfAnalysisRuntime reports a bad path/data combination (a raised ValueError,
# caught and reported generically); ExecutionErrorCategory has no distinct "bad
# arguments" category either.

ApprovalPolicy = Literal["allowed", "approval_required", "rejected"]
# Value-identical to cv_agent.execution.models.ApprovalPolicy (ADR-0009 §3).
# Deliberately duplicated, not imported (§11 finding #12's resolution): importing it
# would create the exact cv_agent.tools -> cv_agent.execution dependency §2/§3
# forbid, and a new shared module solely to deduplicate one three-value Literal would
# be an abstraction introduced for its own sake. Drift is prevented structurally, not
# by convention alone — §7's acceptance test suite must assert
# `set(get_args(ApprovalPolicy)) == set(get_args(cv_agent.execution.models.ApprovalPolicy))`,
# so an edit to one without the other fails a test immediately.

@dataclass(frozen=True)
class ToolInputField:
    name: str
    required: bool
    description: str
    default: Any | None = None
    # Shape mirrors cv_agent.execution.binding.InputField (ADR-0009 §11) exactly,
    # duplicated for the same leaf-package reason as ApprovalPolicy above.

@dataclass(frozen=True)
class ToolRequiredFieldGroup:
    kind: Literal["exactly_one"]
    field_names: tuple[str, ...]
    description: str = ""
    # New (§11 finding #7). Mirrors cv_agent.execution.binding.RequiredFieldGroup
    # (ADR-0009 §12/§13), applying the lesson from Q20 directly instead of repeating
    # its history: "exactly_one" from the start, not a presence-only "at least one"
    # construct later found to under-enforce a real XOR (ADR-0009 §13's own
    # correction). A future planning/orchestration connector must reject 2+ present
    # members as a distinct outcome, exactly as ADR-0010 §15 does for skills — not
    # specified further here, since planning/recovery flows are orchestration's
    # concern (§2), not this boundary's.

@dataclass(frozen=True)
class ToolSpec:
    tool_id: ToolId
    name: str
    description: str
    transport: ToolTransport
    side_effecting: bool
    approval_policy: ApprovalPolicy
    input_schema: tuple[ToolInputField, ...] = ()
    input_field_groups: tuple[ToolRequiredFieldGroup, ...] = ()
    verified: bool = False
    # DECLARED vs VERIFIED — unchanged from the first draft. input_schema and
    # input_field_groups are planning/description metadata ONLY (§11 finding #11,
    # made explicit here per the review's own instruction) — ToolExecutor never
    # validates request.inputs against either. A ToolInvoker implementation (or its
    # own transport-specific validation) is the sole authoritative enforcement layer,
    # exactly as ADR-0009 §11 states for InputField: "planning metadata, not a
    # replacement for runtime validation." __post_init__ (no body — no
    # implementation in an ADR) must validate input_field_groups the same way
    # ExecutionBinding.__post_init__ does (ADR-0009 §12/§13): every field_names entry
    # names a declared, required=False ToolInputField, and no field belongs to more
    # than one group.

    def pin(self) -> dict[str, Any]: ...
    # Canonical snapshot of THIS spec's own fields only — explicit field access,
    # declared order, JSON-native, no asdict()/repr(). Mirrors ExecutionBinding.pin()
    # (ADR-0009 §14). Does not include invoker/generation information — see
    # ToolRegistry.pin() below, which combines the two, mirroring
    # ExecutionBindingRegistry.pin(skill_id)'s combination of binding.pin() +
    # runtime_generation.

@dataclass(frozen=True)
class ToolRequest:
    inputs: dict[str, Any] = field(default_factory=dict)
    requested_by: str = "agent"
    approved: bool = False
    expected_tool_pin: dict[str, Any] | None = None
    # None = not supplied. The expected shape, when supplied, is exactly
    # ToolRegistry.pin(tool_id)'s return value — {"spec": ..., "invoker_generation":
    # ...} — never ToolSpec.pin() alone. Mirrors SkillExecutionRequest.
    # expected_binding_pin (ADR-0009 §14).

@dataclass(frozen=True)
class ToolError:
    category: ToolErrorCategory
    message: str

@dataclass(frozen=True)
class ToolEvidence:
    tool_id: ToolId
    invoker_generation: int | None
    started_at: str | None
    completed_at: str | None
    provenance: dict[str, Any] = field(default_factory=dict)
    execution_metadata: dict[str, Any] = field(default_factory=dict)
    # New (§11 finding #4). Mirrors ExecutionEvidence's role (binding_id/runtime_id/
    # started_at/completed_at, ADR-0009 §5) — invoker_generation stands in for a
    # separate "invoker_id" field deliberately: this boundary's ToolInvoker.tool_id
    # already IS the tool's own identity (a 1:1 tool/invoker model, simpler than
    # ADR-0009's separate skill_id/runtime_id namespaces), so a distinct invoker_id
    # field would just repeat tool_id; the generation number is the genuinely new
    # audit fact worth recording. provenance/execution_metadata are new, deliberately
    # generic placeholder fields (spec/06's "Tool Result Contract": status/result/
    # artifacts/metrics/logs/errors/provenance/execution_metadata, cited in §1 —
    # `[P§25]` reproducibility is the underlying canon reason). Type-level only: no
    # backend, no persistence mechanism, no concrete schema for either dict's
    # contents is chosen here — that is an implementation-PR and/or a future ADR's
    # job (e.g., how this relates to docs/state/EXPERIMENTS.md's `[P§25]` schema is
    # explicitly not decided by this ADR). Populated by ToolExecutor from what IT
    # directly observes (its own clock, the invoker identity/generation it looked
    # up) — never copied from a field the invoker itself sets, preserving the trust
    # boundary described under ToolOutcome below.

@dataclass(frozen=True)
class ToolResult:
    tool_id: ToolId
    status: ToolResultStatus
    evidence: ToolEvidence
    output: dict[str, Any] | None = None
    error: ToolError | None = None
    # Shape now matches SkillExecutionResult (skill_id/status/evidence/output/error,
    # ADR-0009 §5) field-for-field. Constructed ONLY by ToolExecutor — see
    # ToolInvoker/ToolOutcome below (§11 finding #3).

@dataclass(frozen=True)
class ToolOutcome:
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    # New (§11 finding #3). Mirrors RuntimeOutcome (ADR-0009 §5) exactly, for the
    # identical reason: a ToolInvoker reports only whether ITS OWN call succeeded and
    # what it produced — it has no field to set tool_id, status, or evidence with.
    # Those are ToolExecutor's to assign afterward, from what the executor itself
    # knows (the request it made, the identity/generation it looked up, its own
    # clock) — never from data an invoker chooses to hand back. This restores the
    # trust boundary the first draft collapsed by having ToolInvoker.invoke() return
    # ToolResult directly.

# module: cv_agent.tools.invoker
class ToolInvoker(Protocol):
    tool_id: str
    def invoke(self, spec: ToolSpec, request: ToolRequest) -> ToolOutcome: ...
    # Return type changed from ToolResult to ToolOutcome (§11 finding #3). Symmetric
    # in *shape* to ExecutionRuntime.invoke() -> RuntimeOutcome (ADR-0009 §5); still
    # never substitutable for it — no shared base class, no isinstance-compatible
    # substitution (§9). `tool_id` stays a plain `str` attribute here, not `ToolId`:
    # it identifies which invoker instance this is at registration time, mirroring
    # ExecutionRuntime.runtime_id's own plain-str identity (ADR-0009 §5) — the typed
    # `ToolId` is for catalogue-facing identifiers (ToolSpec/ToolResult/registry
    # lookups), not every internal string with the same value.

# module: cv_agent.tools.registry
class ToolRegistry:
    def register_spec(self, spec: ToolSpec) -> None: ...
    def register_invoker(self, invoker: ToolInvoker) -> None: ...
        # Stores (invoker, generation) keyed by invoker.tool_id in one dict, by one
        # assignment — mirrors ExecutionBindingRegistry.register_runtime (ADR-0009
        # §14): no prior entry -> generation 1; prior object `is` the new one ->
        # unchanged; else prior generation + 1. This is the mechanism that makes a
        # replacement ToolInvoker during a paused workflow detectable (§11 finding
        # #1). No removal API exists and none is added, consistent with
        # ExecutionBindingRegistry's own documented limitation (ADR-0009 §14).
    def get_spec(self, tool_id: ToolId) -> ToolSpec | None: ...
    def get_invoker(self, tool_id: ToolId) -> ToolInvoker | None: ...
    def get_invoker_registration(self, tool_id: ToolId) -> tuple[ToolInvoker, int] | None: ...
        # New (§11 finding #1). Instance + generation from ONE dict read;
        # inspect-only. Mirrors ExecutionBindingRegistry.get_runtime_registration()
        # (ADR-0009 §14).
    def list_specs(self) -> list[ToolSpec]: ...
    def list_invokers(self) -> list[ToolInvoker]: ...
        # New (§11 finding #8) — was asymmetric with list_specs() in the first
        # draft; mirrors ExecutionBindingRegistry's list_bindings()/list_runtimes()
        # pair.
    def can_invoke(self, tool_id: ToolId) -> bool: ...
        # False whenever: no spec registered, spec.verified is False, or no invoker
        # is registered for it. Unchanged from the first draft.
    def pin(self, tool_id: ToolId) -> dict[str, Any] | None: ...
        # New (§11 finding #1). {"spec": spec.pin(), "invoker_generation": int |
        # None}; None if no spec is registered. Mirrors
        # ExecutionBindingRegistry.pin(skill_id) (ADR-0009 §14) exactly — the
        # canonical spec snapshot combined with the current invoker generation,
        # captured once by a future caller (orchestration wiring, out of scope here)
        # and carried as ToolRequest.expected_tool_pin across a pause.

def tool_pin_is_well_formed(pin: Any, *, tool_id: ToolId) -> bool: ...
    # New (§11 findings #1/#2). Strict schema check mirroring pin_is_well_formed
    # (ADR-0009 §14): exact keys, types, invoker_generation int>=1|None, spec.tool_id
    # == tool_id.
def tool_pin_mismatch(expected: Any, live: dict[str, Any]) -> tuple[str, ...]: ...
    # New (§11 findings #1/#2). () if equal; ("tool_pin_malformed",) if not
    # well-formed; else sorted "spec.<key>" / "invoker_registration" naming what
    # differs. Equality is canonical-JSON text comparison — the identical algorithm
    # to pin_mismatch (ADR-0009 §14): two independently-typed but functionally
    # identical checks, not two different security models.

# module: cv_agent.tools.executor
class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None: ...
    def can_invoke(self, tool_id: ToolId) -> bool: ...
    def invoke(self, tool_id: ToolId, request: ToolRequest) -> ToolResult: ...
    # Fail-safe branching and ordering now mirrors SkillExecutor.execute() as amended
    # by ADR-0009 §14 (§11 finding #9 — not just its original, simpler shape):
    #   1. spec = registry.get_spec(tool_id); None -> not_executable / no_tool.
    #   2. registration = registry.get_invoker_registration(tool_id) — read ONCE;
    #      invoker and generation both come from this one read.
    #   3. (E1-equivalent) live spec.approval_policy == "approval_required" AND
    #      request.expected_tool_pin is None -> rejected / approval_denied,
    #      REGARDLESS of request.approved — checked before the verified check,
    #      matching ADR-0009 §14's amended order (the first draft checked verified
    #      first — §11 finding #9).
    #   4. pin supplied (for ANY approval_policy, not only approval_required) ->
    #      tool_pin_is_well_formed(...); not well-formed -> not_executable /
    #      tool_mismatch. Else tool_pin_mismatch(pin, {"spec": spec.pin(),
    #      "invoker_generation": generation}); non-empty -> not_executable /
    #      tool_mismatch. The invoker is never called on this path (§11 findings
    #      #1/#2, fail-closed).
    #   5. spec.verified is False -> not_executable / tool_not_verified.
    #   6. spec.approval_policy == "rejected" -> rejected / approval_denied.
    #   7. approval_policy == "approval_required" and not request.approved ->
    #      rejected / approval_denied.
    #   8. no invoker registered -> not_executable / no_tool.
    #   9. otherwise -> invoker.invoke(spec, request) -> ToolOutcome. ToolExecutor
    #      itself constructs the returned ToolResult: tool_id/status from its own
    #      knowledge of the call it just made (never from a field on ToolOutcome,
    #      which has none to offer), evidence.tool_id/invoker_generation/started_at/
    #      completed_at from what the executor observed directly, and
    #      evidence.provenance/execution_metadata left as empty dicts unless a
    #      future implementation defines a populating rule (not decided here — §11
    #      finding #4's "type-level only" constraint). A raised exception from
    #      invoke() is caught and reported as status="failed" / category
    #      "transport_error", never propagated (mirrors SkillExecutor's "catch,
    #      never propagate" posture) and never as "tool_mismatch" — that category is
    #      reserved for step 4's own check, never for an invoker-raised exception.
    # ToolExecutor decides only whether an already-decided call is currently
    # permitted to proceed. It must never decide whether the call should happen at
    # all (§9).
```

## 6. Consequences

- **Enables:** a single, typed place for any future non-skill external interface
  (research fetch, GitHub, filesystem, training-infrastructure status, deployment
  infrastructure) to register against without collapsing into ADR-0009's skill-specific
  types; a well-defined slot for a future real MCP client to occupy as one
  `ToolInvoker` implementation among several possible transports (`local`,
  `subprocess`, `http`, `mcp`); keeps `[P§22]`'s "agent decides what, tool decides how"
  split enforceable in code, not only in prose.
- **Makes harder:** nothing removed — purely additive, mirroring ADR-0009's own framing.
- **Costs:** zero today — this ADR merges no code. Once accepted and implemented: one
  new package, now comparable in size to the combination of `cv_agent/execution/`'s
  models/binding/executor modules (~350–420 lines of types and fail-safe branching,
  larger than the first draft's estimate to account for generation tracking,
  `ToolEvidence`/`ToolOutcome`, and `ToolRequiredFieldGroup` — §11), no new
  third-party dependency for the boundary itself; an actual MCP client, if and when
  one is built, would add its own dependency inside a single `ToolInvoker`
  implementation module, never in `cv_agent/tools/` itself.
- **Migration / blast radius if reversed:** contained — no code exists yet, so reverting
  this ADR means deleting an unimplemented specification and touches nothing else in
  the repository.

## 7. Acceptance test

Implemented in `tests/test_tools.py` (issue #53), satisfying at least (updated per
§11 to cover the review's five IMPORTANT findings):

- `ToolRegistry()` starts empty; `can_invoke("anything")` is `False` and never raises.
- A registered `ToolSpec(verified=False, approval_policy="allowed")` with a registered
  `ToolInvoker` still reports `can_invoke() is False` — verification, not mere
  registration, gates invocability (mirrors `tests/test_execution.py`'s
  unverified-binding case, ADR-0009 §7).
- `ToolExecutor.invoke()` against an unregistered `tool_id` returns
  `ToolResult(status="not_executable", error=ToolError(category="no_tool", ...))` and
  never raises.
- `ToolExecutor.invoke()` against an `approval_required` `ToolSpec` with
  `request.expected_tool_pin is None` returns `status="rejected"` /
  `category="approval_denied"` **regardless of `request.approved`**, and never calls
  `ToolInvoker.invoke()` — asserted via a call-count spy, the tool-layer equivalent of
  ADR-0003 §10's rule E1.
- **New — generation/pin-mismatch (§11 findings #1/#2):** register a spec + invoker,
  capture `registry.pin(tool_id)`, **replace** the registered invoker with a second,
  distinct `ToolInvoker` instance for the same `tool_id`, then call
  `ToolExecutor.invoke()` with the stale, pre-replacement pin as
  `expected_tool_pin` — must return `status="not_executable"` /
  `category="tool_mismatch"`, and **neither** the old nor the new invoker's
  `invoke()` is ever called (call-count spies on both == 0). A second test: an
  identical spec re-registered under an unchanged invoker *object* (`is` the same
  instance) leaves the generation unchanged and the same pin still valid.
- **New — trust boundary (§11 finding #3):** a fake `ToolInvoker` whose `invoke()`
  returns `ToolOutcome(success=True, output={...})` — assert the `ToolResult`
  `ToolExecutor.invoke()` returns has `tool_id`/`status` matching the request actually
  made (not fields the fake could not have set, since `ToolOutcome` has none), and
  `evidence.invoker_generation` matches the registry's recorded generation at
  invocation time.
- **New — `ApprovalPolicy` drift guard (§11 finding #12):** asserts
  `set(get_args(cv_agent.tools.models.ApprovalPolicy)) ==
  set(get_args(cv_agent.execution.models.ApprovalPolicy))`.
- **New — `input_schema` is non-enforcing (§11 finding #11):** a `ToolRequest` whose
  `inputs` omits every `required=True` `ToolInputField` still reaches
  `ToolInvoker.invoke()` (assuming the spec is verified, `allowed`, and no pin
  mismatch) — `ToolExecutor` does not itself validate `inputs` against
  `input_schema`/`input_field_groups`.
- A structural test — mirroring `tests/test_llm_anthropic.py::TestArchitectureBoundary`
  and ADR-0004's `sqlite3`-confinement test — asserting `cv_agent.tools` imports
  nothing from `cv_agent.execution`, `cv_agent.skills`, `cv_agent.graph`, or
  `cv_agent.llm` anywhere in the package.
- A fresh `ToolRegistry()` constructed by application code (not a test fixture) has
  zero specs and zero invokers — mirrors ADR-0009 §3/§7's "constructed empty, nothing
  auto-registers" assertion for `ExecutionBindingRegistry`.

## 8. Revisit trigger

Any of: (a) `OPEN_QUESTIONS.md` Q5's MCP-vs-skill half is answered by the owner for at
least one concrete integration; (b) Phase 2 (knowledge/research) needs its first real
tool (e.g., a research-fetch call) and a first real `ToolSpec`/`ToolInvoker` is
registered — this ADR is now Accepted and implemented (issue #53), but no tool is
registered by that implementation, exactly as ADR-0009 §1 held the line for skills
until `trt-perf-analysis` (D-014); (c) an owner decision is made on whether
ADR-0009's skill `ExecutionRuntime` should eventually be re-expressed in terms of this
ADR's `ToolInvoker` (not decided either way here — see §10).

## 9. Non-negotiables (must hold when this boundary is implemented)

Carried over by design from ADR-0003 §10 and ADR-0009 §14 — stated here so a future
implementer cannot satisfy this ADR's interface while quietly weakening either:

1. Orchestration and reasoning code must call a tool only through `ToolExecutor` —
   never `ToolInvoker.invoke()` directly. Mirrors "never bypass `SkillExecutor`."
2. An `approval_required` `ToolSpec` invoked without `expected_tool_pin` is refused
   before any transport call, unconditionally — no code path may substitute
   `request.approved=True` for a missing pin (ADR-0003 §10's rule E1, restated for
   tools).
3. `ToolExecutor` never fabricates or infers approval from the existence of a request —
   `request.approved` must originate from a real, upstream human decision recorded by
   orchestration, exactly as `docs/APPROVALS.md` already requires for skill execution.
   `spec/06-tooling-and-mcp.md`'s own line states this independently: "the tool layer
   must not infer approval from the existence of a planning request."
4. No `ToolInvoker` implementation may also implement `ExecutionRuntime` (or vice
   versa) without a follow-up ADR — the two boundaries must not be silently merged by
   an implementer taking a shortcut; see §8(c).
5. `ToolExecutor` decides only whether an already-decided call is currently permitted
   to proceed. It must never decide *whether* the agent should call a tool at all —
   that judgment stays upstream, in reasoning plus capability/skill resolution
   (ADR-0001/ADR-0007/ADR-0008), before a `ToolRequest` is ever constructed.
6. **(Added, §11 findings #1/#2.)** A pin/registration-generation mismatch
   (`tool_mismatch`) is checked before any invoker call whenever a pin is supplied —
   for every `approval_policy`, not only `approval_required` — so a caller that
   chooses to pin an `allowed` tool anyway still gets the same replacement-detection
   guarantee. A replaced `ToolInvoker` is never silently invoked under a stale pin.
7. **(Added, §11 finding #3.)** A `ToolInvoker` is never trusted to self-report
   `tool_id`, `status`, or evidence — only `success`/`output`/`error_message` via
   `ToolOutcome`. `ToolExecutor` alone constructs the `ToolResult` envelope handed
   back to any caller. An implementer who has `ToolInvoker.invoke()` return anything
   other than `ToolOutcome`, or has `ToolExecutor` pass an invoker's own fields
   through unchecked into `ToolResult.tool_id`/`status`, violates this ADR.

## 10. Open questions (not resolved by this ADR)

- **`OPEN_QUESTIONS.md` Q5 (MCP-vs-skill half) — explicitly left unresolved, as
  instructed.** This ADR defines *what a Tool is and how it is invoked*; it does not
  decide *which* NVIDIA or other external capabilities should be exposed via a real
  MCP server versus remaining CLI/skill-based. `OPEN_QUESTIONS.md` is not edited by
  this ADR.
- **New, non-blocking:** `[P§22]` and `spec/06-tooling-and-mcp.md` both note that a
  real MCP specification distinguishes *Tools*, *Resources*, *Prompts*, and
  *long-running tasks/extensions* — "according to the selected MCP specification and
  SDK version." This ADR scopes itself deliberately to invocable, side-effect/result-
  bearing operations only (MCP's "tools" concept); it does not model MCP resources or
  prompts, since no SDK/version has been selected (§4, alternative 2, rejected) and
  inventing that mapping now would be guessing ahead of that choice. A future ADR
  amendment should address resources/prompts once a concrete MCP SDK is chosen — this
  is new to this session, raised here rather than silently decided, and does not block
  anything today (nothing in this codebase currently needs an MCP resource or prompt).
- **New, non-blocking:** ADR-0001 remains `Proposed`, not `Accepted` (D-005). This
  ADR's `ToolId` therefore has no accepted upstream identity to unify with yet. If
  ADR-0001 is later accepted, reconciling its `Skill.requires_tools: tuple[ToolId, ...]`
  with this ADR's `ToolId` is a small, additive follow-up, not a redesign (see §5's
  inline note).
- **Untouched, per explicit instruction:** Q2 (where the agent/training runs), Q3
  (restart-survivable approval transport), Q6 (approval-gate cost thresholds), Q10
  (dataset storage/versioning), Q16 (experiment-ledger backend), Q19 (cost-estimation
  mechanism), Q23 / issue #44 (real-skill CLI reachability of the existing interrupt
  kinds). None is resolved, narrowed, or assumed by this ADR.

## 11. Status — architecture review, no blockers, five IMPORTANT findings addressed

An owner-requested architecture review of the first draft (same day, before
acceptance) found **zero BLOCKERs**. It found five IMPORTANT findings (all resolved
in this revision, §3/§5/§7/§9 above) and several MINOR findings (addressed where
listed; a few explicitly left as-is with rationale, per the review's own instruction
not to expand scope). No implementation was written at any point in the review or
this revision; `OPEN_QUESTIONS.md` was not read as needing edits and remains
untouched; Q5's MCP-vs-skill half, and Q2/Q3/Q6/Q10/Q16/Q19/Q23, remain unresolved.

**IMPORTANT — resolved:**

1. Missing runtime/invoker registration-generation protection → `ToolRegistry`
   gained `get_invoker_registration()`/`pin()`, mirroring
   `ExecutionBindingRegistry.get_runtime_registration()` (ADR-0009 §14). §5, §9 rule 6.
2. No `binding_mismatch`-equivalent error category → `ToolErrorCategory` gained
   `tool_mismatch`, naming a registration/pin mismatch only — the same integrity
   check ADR-0003 §10/ADR-0009 §14 enforce for skills, not a different security
   model. §5.
3. `ToolInvoker.invoke()` returned the final `ToolResult` directly, collapsing the
   runtime/executor trust boundary → new `ToolOutcome` type (mirrors
   `RuntimeOutcome`); `ToolExecutor` alone constructs `ToolResult`. §5, §9 rule 7.
4. `ToolResult` carried no provenance/evidence/execution metadata → new
   `ToolEvidence` (mirrors `ExecutionEvidence`) with `provenance`/
   `execution_metadata` as generic, unpopulated placeholder dicts — type-level only,
   no backend or persistence mechanism chosen. §5.
5. `ToolResultStatus` had no in-progress state → added `started`, unreachable from
   any synchronous path described here, reserved for a future async transport,
   mirroring ADR-0009 §3's own treatment. §5.

**Citation error — corrected:** §1's claim that ROADMAP.md Phase 3 names ADR-0005 in
its Scope line was verified false (only Phase 2 does) and corrected.

**MINOR — addressed:**

- `ToolId` now used consistently on every catalogue-facing identifier (`ToolSpec`,
  `ToolResult`, `ToolEvidence`, registry/executor method signatures); `ToolInvoker
  .tool_id` deliberately kept as plain `str` (mirrors `ExecutionRuntime.runtime_id`'s
  own plain-str identity), documented as an intentional distinction, not an
  oversight.
- Added `ToolRequiredFieldGroup` (`exactly_one`), specified correctly from the start
  per the Q20 lesson rather than repeating ADR-0009's presence-only-then-corrected
  history.
- Added `ToolRegistry.list_invokers()`, restoring symmetry with `list_specs()`.
- Renamed `not_available` → `not_executable`, matching `SkillExecutionStatus`; no
  reason existed for the drift.
- `invalid_input` removed (not deferred) with an explicit rationale inline in §5: no
  branch in this boundary ever produces it, and ADR-0009 has no equivalent category
  either.
- `ToolSpec.input_schema`/`input_field_groups` now explicitly documented as
  planning/description metadata only, never enforced by `ToolExecutor` — mirrors
  ADR-0009 §11's identical disclaimer for `InputField`.
- `ApprovalPolicy` duplication is kept (importing it would create the forbidden
  `cv_agent.tools -> cv_agent.execution` dependency; a new shared module would be an
  abstraction introduced only to deduplicate one Literal) — drift is now prevented by
  a required §7 test comparing both Literals' value sets, not by convention alone.
- Added one explicit statement (§2) distinguishing this boundary from LLM-native
  tool/function calling.

**MINOR — deliberately not changed, to avoid unnecessary abstraction:** `ToolSpec`
still models `tool_id` as 1:1 with exactly one spec and one invoker (no
`binding_id`-equivalent second identity layer) — simpler than ADR-0009's
skill_id/binding_id/runtime_id three-level scheme, and nothing in this boundary's
current scope needs multiple candidate implementations of one `tool_id` the way
ADR-0010's `choose_candidate` needed for skills. If that need arises later, it is an
additive follow-up (a `binding_id`-equivalent field), not a reason to add one now.
