# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-15 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) ·
**Health:** green

## Where we are

Doc consistency pass complete (D-006–D-009). `docs/PROJECT.md` is frozen canon.

**Implemented:** Skill discovery + resolution (ADR-0007), requirements analysis +
task decomposition (ADR-0008), skill execution boundary (ADR-0009, zero bindings
registered — see below), orchestration state + human-approval interrupts (ADR-0003).
**Project memory (ADR-0004) — now wired in (this session):**
`cv_agent/memory/` (SQLite-backed `ProjectMemoryStore`, gitignored, durable, SQLite
confined to `sqlite_store.py`) is called from `CVAgent.start_workflow()`/
`resume_workflow()` — `AgentConfig.workspace_root` (caller-resolved, never inferred),
lazy `CVAgent.memory`, a `SessionRecord` per workflow session, and a
`ProjectUnderstandingRevision` on each factual change (equality-based dedup,
excludes LLM prose). `cv_agent/graph/workflow.py` itself is untouched — persistence
wraps the graph invocation in `CVAgent`, kept separate from LangGraph's own
`MemorySaver` checkpoint (ADR-0003, unchanged).

**Still NOT implemented:** any real execution binding (ADR-0009 §5, `0/84`), RAG,
MCP, research subsystem, autonomous training, optimization/deployment/monitoring, an
LLM/semantic resolver, a persistent LangGraph checkpointer (Q3's durability half).
Every capability in `spec/capability_registry.json` is still `status: "planned"`.

## In flight

| Item | Issue | State |
|---|---|---|
| GitHub scaffolding (labels, templates, CI, milestones) | #— | not started |
| ADR-0001 capability model — seed written, needs review | #— | proposed |
| ADR-0003/0007/0008/0009 | #— | accepted (retroactive) |
| ADR-0004 project memory | #— | accepted; implemented AND wired into `CVAgent` |
| First real `ExecutionRuntime` adapter | #— | not started |

## Next 3 actions

1. Verify one real skill end-to-end (candidate: `trt-perf-analysis`'s
   `scripts/run.sh`) and register the first genuinely-verified binding.
2. Human review of `CLAUDE.md`, `docs/architecture/OVERVIEW.md`, all accepted ADRs.
3. Merge `feature/claude/project-memory` (currently unmerged; 247 tests passing).

## Blockers

- None for ADR-0004's own scope (Q1/Q8/Q15 all resolved, now implemented and wired).
  Q3's durable-transport half still blocks a restart-survivable *approval interrupt*
  specifically (needs a persistent LangGraph checkpointer — separate from, and not
  resolved by, project memory's own durability).

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, registering an unverified binding,
unrestricted autonomous execution, merging the two graphs, a second
`ProjectMemoryStore` backend before SQLite is found insufficient — `[P§34]`.
