# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-16 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) ·
**Health:** green

## Where we are

Doc consistency pass complete (D-006–D-009). `docs/PROJECT.md` is frozen canon.
`main` is at `7c284d2` — PR #26–#29 all merged. This branch
(`feature/claude/requirements-skill-links`, unmerged) closes the next gap an
architecture audit found: `RequirementsAnalyzer` computed matched-skill/executable
information on every `analyze()` call and discarded it.

**Implemented:** skill discovery + resolution (ADR-0007, truthful `executable`
status), requirements analysis (ADR-0008, now surfacing matched skills), skill
execution boundary (ADR-0009) with one real, opt-in `ExecutionRuntime`
(`trt-perf-analysis`, CLI-executable via `execute`), orchestration + human-approval
interrupts (ADR-0003), project memory (ADR-0004). **This session:**
`RequirementsAnalysis.skill_links: tuple[SkillLink, ...]` (new top-level field,
`task_component`-scoped, not nested in `CapabilityLink`) — read off the same
`resolve()` call `capability_links` already used, no second resolution pass;
`executable` copied verbatim from the live `SkillMatch.executable` (ADR-0007 §9).
`analyze` gained a "Matched skills" section; still never registers a binding itself.

**Still NOT implemented:** bindings for the other 83 discovered skills, RAG, MCP,
research, autonomous training, optimization/deployment/monitoring, a real LLM
provider (mock only), cost estimation, a persistent LangGraph checkpointer (Q3's
durability half), skill ranking/selection (deliberately out of scope — orchestration's).

## In flight

| Item | Issue | State |
|---|---|---|
| GitHub scaffolding (labels, templates, CI, milestones) | #— | not started |
| ADR-0001 capability model — seed written, needs review | #— | proposed |
| ADR-0003/0007/0008/0009 | #— | accepted (retroactive) |
| `RequirementsAnalysis.skill_links` (ADR-0008 §9) | #— | implemented, unmerged |
| PRs #26–#29 (orchestration/memory/execution binding/execute CLI) | #26–#29 | merged |

## Next 3 actions

1. Review and merge `feature/claude/requirements-skill-links`.
2. A second individually-verified `ExecutionRuntime` adapter (candidate: `gstreamer-pipeline`, per ADR-0009 §9) — inspect, don't assume.
3. Human review of `CLAUDE.md`, `docs/architecture/OVERVIEW.md`, accepted ADRs.

## Blockers

- None for this session's scope (touched only `cv_agent.requirements`). Q3's
  durable-transport half still blocks a restart-survivable *approval interrupt*.

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, cost estimation, registering an
unverified binding, bulk-registering unverified bindings, a second `ExecutionRuntime`/
skill binding, skill ranking/auto-selection, unrestricted autonomous execution,
merging the two graphs before `run()` needs it, a second `ProjectMemoryStore` backend
— `[P§34]`.
