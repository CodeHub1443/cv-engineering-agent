# ADR-0007: Skill discovery + deterministic resolution foundation

- **Status:** Accepted (retroactive — written alongside the implementation it governs,
  per the same allowance ADR-0001 used as a "seed ADR"; this repo has no live GitHub
  issue tracker wired up yet, so there is no issue number to cite)
- **Date:** 2026-09-08
- **Layer:** cross-cutting (skills + orchestration-adjacent)
- **Canon:** `[P§23]`, `[P§15]`, `[P§16]`, `[P§34]`
- **Supersedes / Superseded by:** —
- **Issue:** #TBD

## 1. Context

`docs/roadmap/ROADMAP.md` Phase 3 names this exact deliverable: "ADR-0007 skill
registry & discovery." ADR-0001 established the capability registry as a catalogue of
*declared* relationships (`[P§23]`) but deliberately stopped short of a resolver —
`spec/capability_registry.json`'s `relevant_skills` lists are strings, not proof that
those skills exist anywhere. `docs/state/STATUS.md` (as of the previous session's
correction pass) explicitly lists `SkillSource`, skill discovery, and
`CapabilityResolver` as NOT implemented. This ADR is the boundary for changing that,
scoped narrowly: discovery and a deterministic (non-LLM) resolver only.

## 2. Responsibility (required — `[P§34]`)

- **This owns:** discovering what skills are actually present in the runtime
  environment (`cv_agent.skills.local.LocalSkillSource`), aggregating discovery
  results (`cv_agent.skills.inventory.SkillInventory`), and a deterministic
  keyword-overlap resolution from a natural-language task to declared capabilities and
  discovered skills (`cv_agent.skills.resolver.TaskResolver`).
- **This does NOT own:**
  - deciding whether a matched capability/skill *should* be invoked → reasoning layer
    (not built);
  - actually invoking a skill or tool → tools/MCP layer (not built, `[P§22]`);
  - semantic/LLM-based matching → a future resolver behind the same `TaskResolver`
    input/output shape, explicitly out of scope for this ADR;
  - the capability catalogue's data model → `cv_agent.capabilities.registry`
    (ADR-0001), which this module reads but does not modify.
- **Why this responsibility does not belong to an existing component:** the capability
  registry (ADR-0001) intentionally does not know what's installed — it stores
  declared relationships from a spec file, and mixing in live filesystem discovery
  there would blur "declared" and "discovered" into one concept, which is exactly the
  drift `[P§23]` warns against and which the previous session's audit found and fixed
  once already (capability `status` semantics). Skill discovery needs its own module
  so "discovered" stays a fact about the environment, never a fact inferred from a
  spec file.

## 3. Decision

Three new, narrow types: `Skill` (what discovery found), `SkillSource` (a `Protocol`
for where discovery looks), `SkillInventory` (aggregates sources, dedups by
`skill_id`). One `SkillSource` implementation, `LocalSkillSource`, scanning
`<root>/<skill_id>/SKILL.md` under configurable roots (default: `~/.claude/skills` and
`~/.agents/skills`, matching this machine's actual observed convention; overridable via
`CV_AGENT_SKILL_PATHS`). One resolver, `TaskResolver`, doing pure keyword-overlap
scoring between task text, capability metadata, and skill metadata — no LLM call, no
embedding, no network access. Three new CLI commands (`skills`, `capabilities`,
`resolve`) exposing this without changing the default (no-subcommand) health-check
behavior.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Fold skill discovery into `CapabilityRegistry` | Fewer modules | Conflates "declared in a spec file" with "found on disk" — the exact confusion the prior capability-registry audit (D-009) spent a whole session un-conflating | Would reintroduce the bug that was just fixed |
| LLM-based resolver from the start | Matches the eventual product vision (`[P§30]`) more closely | No LLM provider is wired to anything but a mock (`cv_agent/llm/mock.py`); an LLM resolver here would be unauditable and untestable without network access, and the user's own scope explicitly excludes it | Explicitly out of scope for this task; `TaskResolver`'s interface is designed so a semantic resolver can be swapped in later without changing callers |
| Single global `Plugin` abstraction merging capability/skill/tool/agent | Less code | Directly contradicts `[P§23]` ("these are not interchangeable") and this repo's own architectural rule #11 in the Step 2 task spec | Rejected outright, not built |

## 5. Interface

```python
# module: cv_agent.skills.models
@dataclass(frozen=True)
class SkillEvidence:
    source_id: str
    location: str
    discovered_at: str

@dataclass(frozen=True)
class Skill:
    skill_id: str
    name: str
    description: str
    source: str
    location: str
    tags: tuple[str, ...] = ()
    supported_capabilities: tuple[str, ...] = ()
    compatible_agents: tuple[str, ...] = ()
    discovered: bool = True
    executable: bool = False
    evidence: SkillEvidence | None = None

# module: cv_agent.skills.source
class SkillSource(Protocol):
    source_id: str
    def discover(self) -> list[Skill]: ...

# module: cv_agent.skills.inventory
class SkillInventory:
    def discover(self) -> list[Skill]: ...
    def list(self) -> list[Skill]: ...
    def get(self, skill_id: str) -> Skill | None: ...
    def is_discovered(self, skill_id: str) -> bool: ...

# module: cv_agent.skills.resolver
class TaskResolver:
    def resolve(self, task: str) -> ResolutionResult: ...
```

## 6. Consequences

- **Enables:** `python -m cv_agent resolve "<task>"` producing an evidence-carrying,
  non-fabricated task → capability → skill trace; a place for a future semantic
  resolver and a future `CapabilityResolver` (per `spec/02`-era naming, not built) to
  plug in without a rewrite.
- **Makes harder:** nothing removed; purely additive.
- **Costs:** one new package (`cv_agent/skills/`), ~450 lines, no new third-party
  dependency (the frontmatter parser is hand-rolled specifically to avoid adding
  PyYAML for a flat key:value format — see `local.py`'s docstring).
- **Migration / blast radius if reversed:** contained — `TaskResolver`,
  `SkillInventory`, and the three CLI commands are the only consumers of this module;
  removing it does not touch `CapabilityRegistry`, the LLM gateway, or the graph.

## 7. Acceptance test

`tests/test_skills.py` (frontmatter parsing with/without/malformed frontmatter, local
discovery including missing-root and duplicate-id handling, inventory aggregation,
resolver matching/ranking/missing-skill reporting) and
`tests/test_cli.py::TestCLISkillsCapabilitiesResolve` (all three new CLI commands,
run against an isolated `tmp_path` fixture via `CV_AGENT_SKILL_PATHS`, never the real
machine's skills).

## 8. Revisit trigger

When a second `SkillSource` is needed (repository-local skills, a remote catalog, or
MCP-discovered capabilities per `spec/06-tooling-and-mcp.md`) — **still open** — or
when an actual execution binding is built for any skill (which would need a fourth
state beyond declared/discovered/executable=False to express "executable=True"
honestly, per `docs/state/STATUS.md`'s existing DECLARED != EXECUTABLE invariant) —
**fired, see §9.**

## 9. Status — executable status wiring (amendment)

**Amended (branch `feature/claude/execution-feedback-loop`):** §8's second trigger
fired once ADR-0009 shipped a real, verified `ExecutionBinding` (`trt-perf-analysis`,
D-014) — `Skill.executable`/`SkillMatch.executable` had been hardcoded `False`
everywhere in this package ever since, which was correct *when written* (no binding
existed) but became a stale claim once one did.

- **Dependency-direction decision:** `cv_agent.skills` must not import
  `cv_agent.execution` — `ExecutionBinding`/`ExecutionBindingRegistry` stay concrete
  types this package never names, preserving this ADR's own §2 boundary and
  ADR-0009 §2's mirrored statement that discovery is "unchanged, called by nothing"
  in the execution package. The chosen shape (of the two the owning task offered):
  inject a plain `Callable[[str], bool]` predicate — the same shape
  `SkillExecutor.can_execute`/`CVAgent.can_execute` already expose — rather than
  having the application layer reconstruct `ResolutionResult`/`Skill` trees
  after the fact. No new abstraction: `Callable[[str], bool]` is a stdlib type.
- **Injection point:** `SkillInventory`, not `TaskResolver` directly. `TaskResolver`
  already reads every `Skill` it matches through `SkillInventory.list()`/`.get()`
  (§5's existing interface, unchanged), so making `SkillInventory` the one
  execution-aware point means `SkillMatch.executable` (resolver.py) and the `skills`
  CLI command (which reads `SkillInventory` directly) both become correct from a
  single injection, instead of needing the predicate threaded through two places.
  `TaskResolver._match_skills()` now copies `skill.executable` verbatim rather than
  independently hardcoding `False`.
- **Who wires it:** `CVAgent.__init__` (`cv_agent/runtime/agent.py`) constructs
  `ExecutionBindingRegistry`/`SkillExecutor` before `SkillInventory`, then passes
  `self._executor.can_execute` in. A fresh `CVAgent`'s registry still starts empty
  exactly as ADR-0009 §3 requires, so this reordering changes no externally visible
  default — `skills`/`resolve`/`capabilities`/`executions` still report
  `executable=False` for every skill unless a caller has separately, explicitly
  registered a binding (see ADR-0009 §10).
- **What did not change:** `LocalSkillSource`/`SkillSource.discover()` still
  hardcode `executable=False` at discovery time, per this ADR's original §5
  interface — discovery genuinely has no way to know about execution and never
  will. `SkillInventory(...)` constructed the old way (no `is_executable` given, the
  default) reproduces the exact prior behavior — every existing direct construction
  of it (nearly all of `tests/test_skills.py`) is unaffected.
- **Consequence:** `tests/test_skills.py::test_every_discovered_skill_is_not_executable`
  and `test_resolve_matches_a_discovered_skill`'s `executable is False` assertion
  both remain **correct as written** — neither test wires a predicate in, so both
  still exercise (and correctly assert) the unchanged default path. New tests
  (`TestSkillInventoryExecutableStatus`, plus two resolver-level tests) added the
  missing positive case and the CVAgent-level integration case
  (`tests/test_agent.py::TestExecutableStatusWiring`), rather than rewriting
  assertions that were never wrong.
