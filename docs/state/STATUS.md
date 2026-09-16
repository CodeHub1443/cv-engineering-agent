# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-16 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) ·
**Health:** green

## Where we are

Doc consistency pass complete (D-006–D-009). `docs/PROJECT.md` is frozen canon.
`main` has merged PR #28 (first real execution binding); this branch (PR #27) is
reconciled against it and carries both pieces together, unmerged.

**Implemented:** skill discovery + resolution (ADR-0007), requirements analysis +
task decomposition (ADR-0008), skill execution boundary (ADR-0009) with its **first
real, opt-in `ExecutionRuntime`** (`trt-perf-analysis`; `CVAgent.__init__` still
builds an empty registry, so a fresh agent still reports `0/84` unless a caller opts
in), orchestration state + human-approval interrupts (ADR-0003, a second graph kept
separate from `build_graph()`/`run()`), and **project memory (ADR-0004)**, wired into
`CVAgent.start_workflow()`/`resume_workflow()`: SQLite-backed `ProjectMemoryStore`
(gitignored, durable, `sqlite3` confined to `sqlite_store.py`), a `SessionRecord` per
session, and a `ProjectUnderstandingRevision` on each factual change. LangGraph's
own `MemorySaver` checkpoint (ADR-0003) is unchanged by this.

**Still NOT implemented:** bindings for the other 83 discovered skills, RAG, MCP,
research subsystem, autonomous training, optimization/deployment/monitoring, an
LLM/semantic resolver, a real LLM provider (mock only), a persistent LangGraph
checkpointer (Q3's durability half). Every capability in
`spec/capability_registry.json` is still `status: "planned"`.

## In flight

| Item | Issue | State |
|---|---|---|
| GitHub scaffolding (labels, templates, CI, milestones) | #— | not started |
| ADR-0001 capability model — seed written, needs review | #— | proposed |
| ADR-0003/0007/0008/0009 | #— | accepted (retroactive) |
| First real `ExecutionRuntime` adapter (`trt-perf-analysis`) | #28 | merged to `main` |
| ADR-0004 project memory | #27 | implemented, rebased onto post-#28 `main`, PR open |

## Next 3 actions

1. Merge PR #27 (this branch) now that it is reconciled against `main`.
2. A second individually-verified `ExecutionRuntime` adapter (candidate:
   `gstreamer-pipeline`'s bundled scripts, per ADR-0009 §9) — inspect, don't assume.
3. Human review of `CLAUDE.md`, `docs/architecture/OVERVIEW.md`, ADR-0003/0007/0008/0009.

## Blockers

- None for ADR-0004's own scope (Q1/Q8/Q15 resolved, implemented, wired). Q3's
  durable-transport half still blocks a restart-survivable *approval interrupt*
  (needs a persistent LangGraph checkpointer, separate from memory's own durability).

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, registering an unverified binding,
bulk-registering bindings for skills not individually verified, unrestricted
autonomous execution, merging the two graphs before `run()` needs it, a second
`ProjectMemoryStore` backend before SQLite is found insufficient — `[P§34]`.
