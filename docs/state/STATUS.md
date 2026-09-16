# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-16 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) ·
**Health:** green

## Where we are

Doc consistency pass complete (D-006–D-009). `docs/PROJECT.md` is frozen canon.

**Implemented:** skill discovery + resolution (ADR-0007), requirements analysis +
task decomposition (ADR-0008), skill execution boundary (ADR-0009), orchestration
state + human-approval interrupts (ADR-0003) — `cv_agent/graph/workflow.py`, a real
LangGraph interrupt/resume graph, kept as a **second** graph separate from the
existing `build_graph()`/`run()` stub (ADR-0003 §4/§8). **First real execution
binding (ADR-0009 §9, this session):** `cv_agent/execution/runtimes/
trt_perf_analysis.py` — genuine subprocess invocation of the installed
`trt-perf-analysis` skill's real `scripts/analyze_trt_perf.py`, not simulated.
Registration is explicit/opt-in (`register(registry)`); `CVAgent.__init__` still
constructs an empty registry, so a fresh `CVAgent`'s report is unchanged.

**Still NOT implemented:** bindings for any other skill (83/84 still `0`), project
memory (built and passing on the separate, still-unmerged
`feature/claude/project-memory` branch / PR #27 — not on `main`), RAG, MCP, research
subsystem, autonomous training, optimization/deployment/monitoring, an LLM/semantic
resolver, a real LLM provider (mock only). Every capability in
`spec/capability_registry.json` is still `status: "planned"`.

## In flight

| Item | Issue | State |
|---|---|---|
| GitHub scaffolding (labels, templates, CI, milestones) | #— | not started |
| ADR-0001 capability model — seed written, needs review | #— | proposed |
| ADR-0003/0007/0008/0009 | #— | accepted (retroactive) |
| First real `ExecutionRuntime` adapter (`trt-perf-analysis`) | #— | implemented, opt-in, unmerged (`feature/claude/execution-binding`) |
| ADR-0004 project memory | #27 | implemented, unmerged, PR open |

## Next 3 actions

1. Merge PR #27 and this branch's execution-binding work; reconcile
   `docs/state/DECISIONS.md` D-014 numbering — both branched independently from
   `main` and used the next free number.
2. A second individually-verified `ExecutionRuntime` adapter (candidate:
   `gstreamer-pipeline`'s bundled scripts, per ADR-0009 §9) — inspect, don't assume.
3. Human review of `CLAUDE.md`, `docs/architecture/OVERVIEW.md`, ADR-0003/0007/0008/0009.

## Blockers

- `OPEN_QUESTIONS.md` Q1 blocks ADR-0004 on `main` (already answered on PR #27,
  just not merged); Q3's durable-transport half blocks restart-survivable approval.

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, registering an unverified binding,
bulk-registering bindings for skills not individually verified, unrestricted
autonomous execution, merging the two graphs before `run()` needs it — `[P§34]`.
