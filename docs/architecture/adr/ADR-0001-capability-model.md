# ADR-0001: Typed capability registry and explicit resolution contract

- **Status:** Accepted
- **Date:** 2026-08-30
- **Layer:** cross-cutting
- **Canon:** `[P§23]`, `[P§15]`, `[P§22]`, `[P§34]`, `[P§32]`
- **Issue:** #10

## 1. Context

`[P§23]` states that capability, skill, tool, and agent "are not interchangeable" and
defines the resolution chain `task → capability → skill → tools → execution agent`.
`[P§32]` records that the repository already contains a capability registry with
type-aware identities. The implementation stores heterogeneous registry items in one
registry behind a typed `(item_type, id)` identity; it does not currently implement four
independent persistence registries or an execution resolver.

The architecture must preserve the semantic distinction without prematurely multiplying
storage and lifecycle components. It must also represent a capability that is known but
currently unavailable, including the case where no satisfying skill is installed.

## 2. Responsibility `[P§34]`

The capability registry owns:

- the typed catalogue of what the system can do;
- typed identities for capabilities and supporting entities;
- metadata describing relationships among capabilities, skills, tools, agents, and
  knowledge sources;
- availability metadata used to determine whether a capability may be selected.

It does **not** own:

- deciding whether a capability should be invoked → reasoning layer;
- executing anything → tools / MCP layer;
- procedural know-how → skills;
- workflow sequencing and approval control → orchestration.

## 3. Decision

Use a **single registry storage boundary with typed domain identities**, rather than four
independent persistence registries.

The public model remains semantically distinct:

```text
CapabilityId
SkillId
ToolId
AgentId
```

Registry items are identified internally as `(ItemType, id)`, so the same string may be
used safely by different entity types. A capability may reference zero or more skills,
tools, agents, and knowledge sources without conflating those entities.

The registry will expose an explicit resolution contract as the capability-selection layer
matures:

```python
Resolution = (
    capability,
    selected_skill,
    required_tools,
    available,
    unavailable_reason,
)

resolve(capability_id) -> Resolution
```

Resolution is a domain operation, not an execution operation. It must never execute a tool.
A capability with no satisfying skill remains a valid registry entry and resolves as
`available=False` with an actionable reason rather than raising because the capability is
unknown.

External expertise (for example NVIDIA TAO, TensorRT, DeepStream, CUDA agent) is recorded
as externally-provenanced skills when that integration is implemented. The repository must
not duplicate their procedural knowledge `[P§15]`.

The current baseline therefore keeps `CapabilityRegistry` as the storage/API boundary;
the typed resolution surface is implemented when the Phase 1 capability acceptance tests
require it. This ADR does not authorize that implementation by itself.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Decision |
|---|---|---|---|
| Four independent registries | Mirrors conceptual domains directly | Adds unnecessary persistence/lifecycle boundaries at the current scale | Rejected for V1 substrate |
| Single flat tool registry | Simple and common | Cannot represent known-but-unavailable capabilities or external skills cleanly | Rejected; violates `[P§23]` |
| Single typed registry + explicit resolver contract | Preserves semantic separation while keeping one storage boundary | Requires disciplined typed APIs and resolver tests | **Accepted** |

## 5. Interface contract

```python
from typing import Literal, NewType, NamedTuple, Protocol

CapabilityId = NewType("CapabilityId", str)
SkillId = NewType("SkillId", str)
ToolId = NewType("ToolId", str)
AgentId = NewType("AgentId", str)


class Skill(Protocol):
    id: SkillId
    satisfies: tuple[CapabilityId, ...]
    requires_tools: tuple[ToolId, ...]
    provenance: Literal["internal", "external"]


class Resolution(NamedTuple):
    capability: Capability
    skill: Skill | None
    tools: tuple[ToolId, ...]
    available: bool
    unavailable_reason: str | None


class Registry(Protocol):
    def resolve(self, capability: CapabilityId) -> Resolution: ...
    def capabilities(self, *, stage: str | None = None) -> tuple[Capability, ...]: ...
```

The concrete baseline may use the existing dataclasses and JSON schema until the resolver
is implemented. No provider SDK, tool invocation, or skill execution belongs in this API.

## 6. Consequences

- **Enables:** honest "known but unavailable" answers, cross-type identity safety, and a
  future capability → skill → tools resolution path.
- **Preserves:** the existing registry storage boundary and avoids four premature
  persistence systems.
- **Makes harder:** ad-hoc tool registration without capability metadata. This friction is
  intentional `[P§34]`.
- **Costs:** a small resolver contract and focused acceptance tests in Phase 1.

## 7. Acceptance tests

The Phase 1 implementation must prove:

- a capability with no satisfying skill resolves with `available=False` and a reason;
- an external skill can satisfy a capability and reports `provenance="external"`;
- a capability marked `requires_approval` cannot be executed through orchestration without
  an approval record `[P§24]`;
- cross-type IDs remain distinct and cannot overwrite one another;
- the typed public API prevents a `SkillId` from being accepted where a `CapabilityId` is
  required by static type checking.

## 8. Revisit trigger

Reconsider this ADR if implementation experience shows that independent registry lifecycles
are required for deployment, versioning, authorization, or discovery, or if the resolver
cannot remain a coherent boundary without introducing those separate stores.
