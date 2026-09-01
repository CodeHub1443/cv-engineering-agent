# ADR-0001: Capability / Skill / Tool / Agent as four distinct registries

- **Status:** Proposed — *seed ADR, written as a worked example of the required form.
  Review and accept, amend, or reject before building on it.*
- **Date:** 2026-08-30
- **Layer:** cross-cutting
- **Canon:** `[P§23]`, `[P§15]`, `[P§22]`, `[P§34]`, `[P§32]`
- **Issue:** #TBD

## 1. Context

`[P§23]` states that capability, skill, tool, and agent "are not interchangeable" and
defines the resolution chain `task → capability → skill → tools → execution agent`.
`[P§32]` records that the existing repository already has a capability registry with
type-safe identities. The risk is the common failure where these four collapse into one
"tools" dictionary, after which `[P§15]`'s rule — know that NVIDIA capabilities exist and
select them rather than duplicating them — becomes unenforceable, because there is no
place to record "this capability is satisfied by an external skill."

## 2. Responsibility `[P§34]`

- **Owns:** the typed catalogue of what the system can do, and the resolution from a
  required capability to the skill and tools that satisfy it.
- **Does NOT own:**
  - deciding *whether* a capability should be invoked → reasoning layer;
  - executing anything → tools / MCP layer;
  - the procedural know-how of a capability → skills;
  - workflow sequencing → orchestration.
- **Why not elsewhere:** reasoning must be able to ask "what can this system do?" without
  importing every execution backend. Orchestration must be able to check a capability is
  available before entering a stage. Neither can own the catalogue without acquiring the
  other's concerns.

## 3. Decision

Four separate registries with distinct identity types — `CapabilityId`, `SkillId`,
`ToolId`, `AgentId` — and an explicit resolver. A capability declares *what*; zero or
more skills declare they *satisfy* a capability and *how*; skills declare the tools they
require; an execution agent is bound at invocation. A capability with no satisfying skill
is a first-class state ("known but unavailable") that the reasoning layer can report
rather than a lookup failure. External capabilities (NVIDIA TAO, DeepStream, TensorRT,
CUDA agent) register as skills with an `external` provenance marker, satisfying `[P§15]`
without duplicating their implementation.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Single tool registry (LangChain-style flat tools) | Simplest; standard in the ecosystem | Cannot express "capability exists, no skill available"; no place to hang external NVIDIA skills | Violates `[P§23]` explicitly; makes `[P§15]` unenforceable |
| Capability + tool only (skills folded into capabilities) | Fewer moving parts | Procedural knowledge ends up inline in capability definitions, which is the "hundreds of hardcoded prompts" failure `[P§31]` | Collapses the distinction the canon calls critical |
| Registry per layer, no central resolver | Loose coupling | Resolution logic duplicates in every caller; no single answer to "what can this system do?" | Reasoning layer needs one catalogue |

## 5. Interface

```python
# module: cv_agent.capabilities

CapabilityId = NewType("CapabilityId", str)   # e.g. "model.optimize.quantization"
SkillId      = NewType("SkillId", str)
ToolId       = NewType("ToolId", str)
AgentId      = NewType("AgentId", str)

class Capability(Protocol):
    id: CapabilityId
    stage: Stage                  # [P§6]
    description: str
    requires_approval: bool       # [P§24]

class Skill(Protocol):
    id: SkillId
    satisfies: tuple[CapabilityId, ...]
    requires_tools: tuple[ToolId, ...]
    provenance: Literal["internal", "external"]   # [P§15]

class Resolution(NamedTuple):
    capability: Capability
    skill: Skill | None
    tools: tuple[ToolId, ...]
    available: bool
    unavailable_reason: str | None

class Registry(Protocol):
    def resolve(self, capability: CapabilityId) -> Resolution: ...
    def capabilities(self, *, stage: Stage | None = None) -> tuple[Capability, ...]: ...
```

## 6. Consequences

- **Enables:** honest "I know this is possible but cannot do it yet" answers; external
  skills as first-class; capability-gated stage entry in orchestration.
- **Makes harder:** adding a quick one-off tool now requires declaring a capability.
  This friction is intentional `[P§34]`.
- **Costs:** small; registry code and its tests.
- **If reversed:** contained — the resolver is the only consumer-facing surface.

## 7. Acceptance test

`tests/capabilities/test_resolution.py`

- a capability with no satisfying skill resolves with `available=False` and a reason,
  and does **not** raise;
- an external skill satisfies its capability and reports `provenance="external"`;
- a capability marked `requires_approval` cannot be executed through the orchestration
  layer without an approval record (`docs/APPROVALS.md`);
- registry identities are type-distinct: passing a `SkillId` where a `CapabilityId` is
  expected fails `mypy`.

## 8a. Interim correction (does not implement this ADR)

The pre-existing `cv_agent/capabilities/registry.py` (predates this ADR, per
`docs/state/STATUS.md`) does not implement the `Resolution`/`resolve()` design in §5 —
no `CapabilityResolver`, skill discovery, or binding mechanism exists. It was, however,
found to violate this ADR's own §3 principle ("known but unavailable" as a first-class
state): its JSON data marked every capability `status: "available"` with zero
executable skill/tool bindings behind any of them, and `check_item()` hardcoded
`available: True` unconditionally.

This was corrected at the data/semantics level only — `status` now distinguishes
`planned` (declared, no executable binding) from `available` (declared AND a verified
executable binding exists), and `check_item()` reports `executable: False` honestly.
Every capability and registry item is currently `planned` / non-executable. This is
the smallest correction consistent with §3's intent; it does not build the `Resolution`
type, `resolve()` method, or typed `SkillId`/`ToolId`/`AgentId` this ADR specifies —
that remains future work under this ADR once accepted.

## 8. Revisit trigger

If, after the first three stage workflows are built, no capability is ever satisfied by
more than one skill, the skill layer is redundant and this ADR should be reconsidered.
